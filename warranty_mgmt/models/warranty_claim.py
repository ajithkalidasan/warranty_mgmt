from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .workflow import WORKFLOW_TOKEN


class WarrantyClaim(models.Model):
    _name = "warranty.claim"
    _description = "Warranty Claim"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "claim_date desc, id desc"

    name = fields.Char(default="New", copy=False, readonly=True, index=True)
    coverage_id = fields.Many2one("warranty.coverage", required=True, ondelete="cascade", index=True, tracking=True)
    partner_id = fields.Many2one("res.partner", ondelete="restrict", index=True, tracking=True)
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict", index=True, tracking=True)
    lot_id = fields.Many2one("stock.lot", ondelete="restrict", index=True, tracking=True)
    policy_id = fields.Many2one(related="coverage_id.policy_id", store=True, readonly=True)
    claim_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    description = fields.Text(required=True)
    diagnosis = fields.Text()
    decision_note = fields.Text()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("resolved", "Resolved"),
        ],
        required=True,
        default="draft",
        tracking=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        required=True,
        index=True,
    )
    company_id = fields.Many2one(related="coverage_id.company_id", store=True, readonly=True)

    _name_uniq = models.Constraint(
        "unique(name)",
        "The warranty claim reference must be unique.",
    )

    @api.onchange("coverage_id")
    def _onchange_coverage_id(self):
        for claim in self:
            if claim.coverage_id:
                claim.product_id = claim.coverage_id.product_id
                claim.lot_id = claim.coverage_id.lot_id
                claim.partner_id = claim.coverage_id.partner_id

    @api.constrains("coverage_id", "product_id", "lot_id")
    def _check_claim_matches_coverage(self):
        for claim in self:
            if claim.coverage_id.product_id != claim.product_id:
                raise ValidationError(_("The claim product must match the warranty coverage product."))
            if claim.coverage_id.lot_id and claim.coverage_id.lot_id != claim.lot_id:
                raise ValidationError(_("The claim lot or serial number must match the warranty coverage lot."))
            if claim.coverage_id.partner_id and claim.coverage_id.partner_id != claim.partner_id:
                raise ValidationError(_("The claim partner must match the warranty coverage partner."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise UserError(_("Claims must be created in draft and moved through the claim workflow."))
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("warranty_mgmt.claim") or "New"
            if vals.get("coverage_id"):
                coverage = self.env["warranty.coverage"].browse(vals["coverage_id"])
                vals.setdefault("product_id", coverage.product_id.id)
                vals.setdefault("lot_id", coverage.lot_id.id)
                vals.setdefault("partner_id", coverage.partner_id.id)
        claims = super().create(vals_list)
        for claim in claims:
            claim.coverage_id._log_history("claim_created", _("Claim %s created.") % claim.display_name)
        return claims

    def write(self, vals):
        if "state" in vals and self.env.context.get("_warranty_internal_transition") is not WORKFLOW_TOKEN:
            raise UserError(_("Change claim status using the workflow actions."))
        if {"coverage_id", "product_id", "lot_id", "partner_id"}.intersection(vals) and any(self.ids):
            raise UserError(_("Claim coverage and product details cannot be changed after creation."))
        previous_states = {claim.id: claim.state for claim in self}
        result = super().write(vals)
        for claim in self:
            if previous_states[claim.id] != claim.state:
                claim.coverage_id._log_history(
                    "claim_state_changed",
                    _("Claim %s state changed from %s to %s.") % (
                        claim.display_name,
                        previous_states[claim.id],
                        claim.state,
                    ),
                )
        return result

    def unlink(self):
        if not self.env.context.get("module_uninstall"):
            raise UserError(_("Claims are retained for audit and cannot be deleted."))
        return super().unlink()

    @api.model
    def create_claim(self, vals):
        vals = dict(vals or {})
        coverage = self.env["warranty.coverage"].browse(vals["coverage_id"]) if vals.get("coverage_id") else False
        if not coverage and vals.get("lot_id"):
            coverage = self.env["warranty.coverage"].validate_warranty(
                vals["lot_id"],
                product_id=vals.get("product_id"),
                partner_id=vals.get("partner_id"),
            )
        if not coverage:
            raise ValidationError(_("A valid warranty coverage is required to create a claim."))
        vals.setdefault("coverage_id", coverage.id)
        vals.setdefault("product_id", coverage.product_id.id)
        vals.setdefault("lot_id", coverage.lot_id.id)
        vals.setdefault("partner_id", coverage.partner_id.id)
        return self.create(vals)

    def action_submit(self):
        for claim in self:
            if claim.state != "draft":
                continue
            if not claim.coverage_id._is_within_claim_window():
                raise UserError(_("This warranty is outside its claim period."))
            claim.coverage_id._check_claim_limit(exclude_claims=claim)
            claim.with_context(_warranty_internal_transition=WORKFLOW_TOKEN).write({"state": "submitted"})
            claim.coverage_id._log_history("claim_submitted", _("Claim %s submitted.") % claim.display_name)
        return True

    def action_approve(self):
        if not self.env.user.has_group("warranty_mgmt.group_warranty_manager"):
            raise UserError(_("Only a warranty manager can approve claims."))
        for claim in self:
            if claim.state != "submitted":
                continue
            if not claim.coverage_id._is_within_claim_window():
                raise UserError(_("This warranty is no longer valid for claim approval."))
            claim.coverage_id._check_claim_limit(exclude_claims=claim)
            claim.with_context(_warranty_internal_transition=WORKFLOW_TOKEN).write({"state": "approved"})
            claim.coverage_id._set_state("claimed")
            claim.coverage_id._log_history("claim_approved", _("Claim %s approved.") % claim.display_name)
        return True

    def action_reject(self):
        if not self.env.user.has_group("warranty_mgmt.group_warranty_manager"):
            raise UserError(_("Only a warranty manager can reject claims."))
        for claim in self:
            if claim.state != "submitted":
                continue
            if not claim.decision_note:
                raise UserError(_("Add a decision note before rejecting the claim."))
            claim.with_context(_warranty_internal_transition=WORKFLOW_TOKEN).write({"state": "rejected"})
            other_live_claims = claim.coverage_id.claim_ids.filtered(
                lambda item: item.id != claim.id and item.state in ("submitted", "approved")
            )
            if not other_live_claims:
                next_state = "expired" if fields.Date.context_today(self) >= claim.coverage_id.expiry_date else "active"
                claim.coverage_id._set_state(next_state)
            claim.coverage_id._log_history("claim_rejected", _("Claim %s rejected.") % claim.display_name)
        return True

    def action_resolve(self):
        if not self.env.user.has_group("warranty_mgmt.group_warranty_manager"):
            raise UserError(_("Only a warranty manager can resolve claims."))
        for claim in self:
            if claim.state != "approved":
                continue
            claim.with_context(_warranty_internal_transition=WORKFLOW_TOKEN).write({"state": "resolved"})
            other_approved = claim.coverage_id.claim_ids.filtered(
                lambda item: item.id != claim.id and item.state == "approved"
            )
            next_state = "claimed" if other_approved else (
                "expired" if fields.Date.context_today(self) >= claim.coverage_id.expiry_date else "active"
            )
            claim.coverage_id._set_state(next_state)
            claim.coverage_id._log_history("claim_resolved", _("Claim %s resolved.") % claim.display_name)
        return True

