from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .workflow import WORKFLOW_TOKEN


class WarrantyCoverage(models.Model):
    _name = "warranty.coverage"
    _description = "Warranty Coverage"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(default="New", copy=False, readonly=True, index=True)
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict", index=True, tracking=True)
    lot_id = fields.Many2one("stock.lot", ondelete="restrict", index=True, tracking=True, check_company=True)
    partner_id = fields.Many2one("res.partner", ondelete="restrict", index=True, tracking=True)
    policy_id = fields.Many2one("warranty.policy", required=True, ondelete="restrict", index=True, tracking=True)
    type_id = fields.Many2one("warranty.type", required=True, ondelete="restrict", index=True, tracking=True)
    warranty_origin = fields.Selection(
        [
            ("sale", "Sale"),
            ("repair", "Repair"),
            ("purchase", "Vendor"),
            ("other", "Other"),
        ],
        string="Origin",
        required=True,
        default="other",
        index=True,
        tracking=True,
        help="What this warranty was granted for. A product sold to the customer is a "
             "'Sale' warranty; parts fitted during a repair are a 'Repair' warranty; a "
             "warranty received from a supplier is a 'Vendor' warranty. Sale and repair "
             "warranties can both reach the same invoice, so the origin keeps them apart.",
    )
    source_model = fields.Char(index=True)
    source_id = fields.Integer(index=True)
    source_ref = fields.Char(index=True)
    start_date = fields.Date(required=True, tracking=True, default=fields.Date.context_today)
    expiry_date = fields.Date(required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("claimed", "Claimed"),
            ("void", "Void"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        tracking=True,
        index=True,
    )
    pre_expiry_notified = fields.Boolean(default=False, readonly=True)
    expiry_notified = fields.Boolean(default=False, readonly=True)
    claim_count = fields.Integer(compute="_compute_claim_count", store=True)
    claim_ids = fields.One2many("warranty.claim", "coverage_id", string="Claims")
    history_ids = fields.One2many("warranty.history", "coverage_id", string="History")
    user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        required=True,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    can_create_claim = fields.Boolean(compute="_compute_can_create_claim")

    _name_uniq = models.Constraint(
        "unique(name)",
        "The warranty coverage reference must be unique.",
    )

    @api.depends("claim_ids.state")
    def _compute_claim_count(self):
        relevant_states = {"submitted", "approved", "resolved"}
        for coverage in self:
            coverage.claim_count = len(coverage.claim_ids.filtered(lambda claim: claim.state in relevant_states))

    @api.depends("state", "start_date", "expiry_date", "policy_id.grace_days")
    def _compute_can_create_claim(self):
        today = fields.Date.context_today(self)
        for coverage in self:
            coverage.can_create_claim = coverage._is_within_claim_window(today)

    @api.onchange("policy_id")
    def _onchange_policy_id(self):
        for coverage in self:
            if coverage.policy_id:
                coverage.type_id = coverage.policy_id.warranty_type_id
                if not coverage.expiry_date and coverage.start_date:
                    coverage.expiry_date = coverage._compute_expiry(
                        start_date=coverage.start_date,
                        policy=coverage.policy_id,
                    )

    @api.onchange("lot_id")
    def _onchange_lot_id(self):
        for coverage in self:
            if coverage.lot_id and not coverage.product_id:
                coverage.product_id = coverage.lot_id.product_id

    @api.constrains("product_id", "lot_id")
    def _check_lot_product(self):
        for coverage in self:
            if coverage.lot_id.product_id and coverage.lot_id.product_id != coverage.product_id:
                raise ValidationError(_("The selected lot or serial number does not belong to the selected product."))

    @api.constrains("policy_id", "type_id")
    def _check_policy_type(self):
        for coverage in self:
            if coverage.policy_id and coverage.type_id != coverage.policy_id.warranty_type_id:
                raise ValidationError(_("The warranty type must match the selected policy."))

    @api.constrains("start_date", "expiry_date")
    def _check_dates(self):
        for coverage in self:
            if coverage.expiry_date and coverage.start_date and coverage.expiry_date <= coverage.start_date:
                raise ValidationError(_("The expiry date must be later than the start date."))

    @api.constrains("lot_id", "state")
    def _check_duplicate_active_warranty(self):
        blocking_states = ("active", "claimed")
        for coverage in self.filtered(lambda item: item.state in blocking_states and item.lot_id):
            # Serialize competing grants for the same serial, origin, and company.
            lock_key = "%s:%s:%s" % (coverage.company_id.id, coverage.warranty_origin, coverage.lot_id.id)
            self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [lock_key])
            duplicates = self.sudo().search_count(
                [
                    ("id", "!=", coverage.id),
                    ("lot_id", "=", coverage.lot_id.id),
                    ("company_id", "=", coverage.company_id.id),
                    ("warranty_origin", "=", coverage.warranty_origin),
                    ("state", "in", blocking_states),
                ]
            )
            if duplicates:
                raise ValidationError(
                    _("Only one current warranty can exist for the same lot or serial number.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft" and self.env.context.get("_warranty_internal_create") is not WORKFLOW_TOKEN:
                raise UserError(_("Create warranties in draft, then activate them through the workflow."))
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("warranty_mgmt.coverage") or "New"
            if vals.get("lot_id") and not vals.get("product_id"):
                lot = self.env["stock.lot"].browse(vals["lot_id"])
                vals["product_id"] = lot.product_id.id
            if vals.get("policy_id") and not vals.get("type_id"):
                policy = self.env["warranty.policy"].browse(vals["policy_id"])
                vals["type_id"] = policy.warranty_type_id.id
            if vals.get("start_date") and vals.get("policy_id") and not vals.get("expiry_date"):
                policy = self.env["warranty.policy"].browse(vals["policy_id"])
                vals["expiry_date"] = self._compute_expiry(vals["start_date"], policy)
            if vals.get("source_model") and vals.get("source_id") and not vals.get("source_ref"):
                vals["source_ref"] = "%s,%s" % (vals["source_model"], vals["source_id"])
        records = super().create(vals_list)
        for record in records:
            record._log_history("created", _("Warranty record created."))
            if record.state == "active":
                record._log_history("activated", _("Warranty activated on creation."))
        return records

    def write(self, vals):
        if "state" in vals and self.env.context.get("_warranty_internal_transition") is not WORKFLOW_TOKEN:
            raise UserError(_("Change warranty status using the workflow actions."))
        protected = {
            "name", "product_id", "lot_id", "warranty_origin", "source_model", "source_id",
            "source_ref", "partner_id", "company_id", "account_move_id", "account_move_line_id",
            "purchase_order_id", "purchase_order_line_id",
        }
        if protected.intersection(vals) and any(record.id for record in self):
            raise UserError(_("Warranty identity and source fields cannot be changed after creation."))
        tracked_fields = {
            record.id: {
                "state": record.state,
                "start_date": record.start_date,
                "expiry_date": record.expiry_date,
                "policy_id": record.policy_id.id,
                "partner_id": record.partner_id.id,
            }
            for record in self
        }
        result = super().write(vals)
        for record in self:
            previous = tracked_fields[record.id]
            if previous["state"] != record.state:
                record._log_history("state_changed", _("State changed from %s to %s.") % (previous["state"], record.state))
            if previous["start_date"] != record.start_date or previous["expiry_date"] != record.expiry_date:
                record._log_history(
                    "dates_updated",
                    _("Coverage dates updated to %s - %s.") % (record.start_date, record.expiry_date),
                )
            if previous["policy_id"] != record.policy_id.id:
                record._log_history("policy_changed", _("Warranty policy changed to %s.") % record.policy_id.display_name)
            if previous["partner_id"] != record.partner_id.id:
                record._log_history("customer_changed", _("Warranty customer was updated."))
        return result

    def _set_state(self, state, extra_vals=None):
        vals = dict(extra_vals or {})
        vals["state"] = state
        return self.with_context(_warranty_internal_transition=WORKFLOW_TOKEN).write(vals)

    def unlink(self):
        if not self.env.context.get("module_uninstall"):
            raise UserError(_("Warranty records are retained for audit. Cancel or void the warranty instead."))
        return super().unlink()

    @api.model
    def _find_matching_policy(self, product):
        if not product:
            return self.env["warranty.policy"]
        template = product.product_tmpl_id
        if hasattr(template, "warranty_enabled") and not template.warranty_enabled:
            return self.env["warranty.policy"]
        if hasattr(template, "warranty_policy_id") and template.warranty_policy_id and template.warranty_policy_id.active:
            return template.warranty_policy_id
        policies = self.env["warranty.policy"].search(
            [("active", "=", True), ("auto_create", "=", True)],
            order="apply_on, id",
        )
        product_specific = policies.filtered(lambda policy: policy.apply_on == "product" and product in policy.product_ids)
        if product_specific:
            return product_specific[:1]
        category_specific = policies.filtered(
            lambda policy: policy.apply_on == "category" and product.categ_id in policy.category_ids
        )
        if category_specific:
            return category_specific[:1]
        return policies.filtered(lambda policy: policy.apply_on == "all")[:1]

    @api.model
    def _compute_expiry(self, start_date, policy=None):
        policy = policy or self.policy_id
        if not policy:
            raise ValidationError(_("A warranty policy is required to compute the expiry date."))
        if not start_date:
            raise ValidationError(_("A start date is required to compute the expiry date."))
        start_date = fields.Date.to_date(start_date)
        delta_map = {
            "day": relativedelta(days=policy.duration),
            "week": relativedelta(weeks=policy.duration),
            "month": relativedelta(months=policy.duration),
            "year": relativedelta(years=policy.duration),
        }
        return start_date + delta_map[policy.duration_unit]

    @api.model
    def create_warranty(self, vals):
        vals = dict(vals or {})
        lot = self.env["stock.lot"].browse(vals["lot_id"]) if vals.get("lot_id") else self.env["stock.lot"]
        product = self.env["product.product"].browse(vals["product_id"]) if vals.get("product_id") else lot.product_id
        if not product:
            raise ValidationError(_("A product is required to create a warranty."))
        vals["product_id"] = product.id
        policy = self.env["warranty.policy"].browse(vals["policy_id"]) if vals.get("policy_id") else self._find_matching_policy(product)
        if not policy:
            raise ValidationError(_("No active warranty policy could be determined for the selected product."))
        vals.setdefault("policy_id", policy.id)
        vals.setdefault("type_id", policy.warranty_type_id.id)
        start_date = vals.get("start_date") or vals.get("source_date")
        if not start_date:
            start_date = fields.Date.context_today(self)
        vals["start_date"] = fields.Date.to_date(start_date)
        vals.setdefault("expiry_date", self._compute_expiry(vals["start_date"], policy))
        vals.setdefault("state", "active")
        return self.with_context(_warranty_internal_create=WORKFLOW_TOKEN).create(vals)

    @api.model
    def validate_warranty(self, lot_id=None, product_id=None, partner_id=None):
        today = fields.Date.context_today(self)
        lot = lot_id.id if hasattr(lot_id, "id") else lot_id
        product = product_id.id if hasattr(product_id, "id") else product_id
        partner = partner_id.id if hasattr(partner_id, "id") else partner_id
        if not lot and not product:
            return False
        domain = [("state", "not in", ("void", "cancelled"))]
        if lot:
            domain.append(("lot_id", "=", lot))
        if product:
            domain.append(("product_id", "=", product))
        if partner:
            domain += ["|", ("partner_id", "=", False), ("partner_id", "=", partner)]
        coverages = self.search(domain, order="start_date desc, id desc", limit=20)
        return next((record for record in coverages if record._is_within_claim_window(today)), False)

    def _is_within_claim_window(self, current_date=None):
        self.ensure_one()
        current_date = fields.Date.to_date(current_date or fields.Date.context_today(self))
        if self.state in ("void", "cancelled"):
            return False
        if not self.start_date or not self.expiry_date or current_date < self.start_date:
            return False
        grace_limit = self.expiry_date + relativedelta(days=self.policy_id.grace_days or 0)
        return current_date < grace_limit

    def _get_notification_users(self):
        users = self.mapped("user_id")
        for xmlid in ("warranty_mgmt.group_warranty_manager", "warranty_mgmt.group_warranty_admin"):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        return users.filtered(lambda user: user.active)

    def _schedule_notification_activity(self, summary, note):
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not activity_type:
            return
        for coverage in self:
            for user in coverage._get_notification_users():
                existing = self.env["mail.activity"].search(
                    [
                        ("res_model", "=", coverage._name),
                        ("res_id", "=", coverage.id),
                        ("activity_type_id", "=", activity_type.id),
                        ("summary", "=", summary),
                        ("user_id", "=", user.id),
                    ],
                    limit=1,
                )
                if existing:
                    continue
                coverage.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=note,
                )

    def _notify_pre_expiry(self):
        for coverage in self.filtered(lambda item: not item.pre_expiry_notified):
            body = _("Warranty %s will expire on %s.") % (coverage.display_name, coverage.expiry_date)
            coverage.message_post(body=body, subtype_xmlid="mail.mt_note")
            coverage._schedule_notification_activity(_("Warranty Expiry Reminder"), body)
            coverage.write({"pre_expiry_notified": True})
            coverage._log_history("pre_expiry_notified", body)

    def _notify_expiry(self):
        for coverage in self.filtered(lambda item: not item.expiry_notified):
            body = _("Warranty %s has expired on %s.") % (coverage.display_name, coverage.expiry_date)
            coverage.message_post(body=body, subtype_xmlid="mail.mt_note")
            coverage._schedule_notification_activity(_("Warranty Expired"), body)
            coverage.write({"expiry_notified": True})
            coverage._log_history("expiry_notified", body)

    def _log_history(self, event, note=None, user_id=None):
        history_model = self.env["warranty.history"].sudo()
        for coverage in self:
            history_model.with_context(_warranty_internal_create=WORKFLOW_TOKEN).create(
                {
                    "coverage_id": coverage.id,
                    "event": event,
                    "note": note or False,
                    "user_id": user_id or self.env.user.id,
                }
            )

    def _check_claim_limit(self, exclude_claims=None):
        # The claim being submitted/approved is excluded from the count: at
        # approval it is already in a counted state ("submitted"), so without
        # this it would count itself and block the very first claim.
        exclude_ids = set(exclude_claims.ids) if exclude_claims else set()
        for coverage in self:
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ["warranty-claim-limit:%s" % coverage.id],
            )
            coverage.invalidate_recordset(["claim_ids"])
            coverage.claim_ids.invalidate_recordset(["state"])
            active_claims = coverage.claim_ids.filtered(
                lambda claim: claim.id not in exclude_ids
                and claim.state in ("submitted", "approved", "resolved")
            )
            if not coverage.policy_id.allow_multiple_claims and active_claims:
                raise UserError(_("This warranty policy only allows one claim."))
            if coverage.policy_id.allow_multiple_claims and len(active_claims) >= coverage.policy_id.max_claims:
                raise UserError(_("The maximum number of allowed claims has already been reached for this warranty."))

    def action_activate(self):
        for coverage in self:
            if coverage.state not in ("draft", "cancelled"):
                continue
            if coverage.expiry_date <= fields.Date.context_today(self):
                raise UserError(_("You cannot activate a warranty that is already expired."))
            coverage._set_state("active", {"pre_expiry_notified": False, "expiry_notified": False})
            coverage._log_history("activated", _("Warranty activated manually."))
        return True

    def extend_warranty(self, additional_duration=None, additional_unit=None, new_expiry_date=None, note=None):
        if not self.env.user.has_group("warranty_mgmt.group_warranty_manager"):
            raise UserError(_("Only a warranty manager can extend a warranty."))
        for coverage in self:
            if coverage.state in ("void", "cancelled"):
                raise UserError(_("Only active, claimed, or expired warranties can be extended."))
            if not new_expiry_date and (additional_duration is not None and additional_duration <= 0):
                raise UserError(_("The extension duration must be greater than zero."))
            if new_expiry_date:
                expiry_date = fields.Date.to_date(new_expiry_date)
            else:
                duration = additional_duration or coverage.policy_id.duration
                duration_unit = additional_unit or coverage.policy_id.duration_unit
                if duration_unit not in ("day", "week", "month", "year"):
                    raise UserError(_("Choose a valid duration unit."))
                delta_map = {
                    "day": relativedelta(days=duration),
                    "week": relativedelta(weeks=duration),
                    "month": relativedelta(months=duration),
                    "year": relativedelta(years=duration),
                }
                expiry_date = coverage.expiry_date + delta_map[duration_unit]
            coverage._set_state("active", {
                "expiry_date": expiry_date,
                "pre_expiry_notified": False,
                "expiry_notified": False,
            })
            coverage.message_post(body=_("Warranty extended until %s.") % expiry_date, subtype_xmlid="mail.mt_note")
            coverage._log_history("extended", note or _("Warranty extended until %s.") % expiry_date)
        return True

    def void_warranty(self, reason=None):
        for coverage in self:
            if coverage.state == "void":
                continue
            if not self.env.user.has_group("warranty_mgmt.group_warranty_manager"):
                raise UserError(_("Only a warranty manager can void a warranty."))
            if coverage.claim_ids.filtered(lambda claim: claim.state in ("submitted", "approved")):
                raise UserError(_("Resolve open claims before voiding this warranty."))
            coverage._set_state("void")
            coverage.message_post(body=reason or _("Warranty was voided."), subtype_xmlid="mail.mt_note")
            coverage._log_history("voided", reason or _("Warranty was voided."))
        return True

    def action_cancel(self):
        for coverage in self:
            if coverage.state in ("void", "expired"):
                raise UserError(_("Expired or void warranties cannot be cancelled."))
            if coverage.claim_ids.filtered(lambda claim: claim.state in ("submitted", "approved")):
                raise UserError(_("Resolve open claims before cancelling this warranty."))
            coverage._set_state("cancelled")
            coverage._log_history("cancelled", _("Warranty was cancelled."))
        return True

    def action_create_claim(self):
        self.ensure_one()
        if not self.env.user.has_group("warranty_mgmt.group_warranty_user"):
            raise UserError(_("You need Warranty User access to create a claim."))
        if not self._is_within_claim_window():
            raise UserError(_("This warranty is outside its claim period."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Warranty Claim"),
            "res_model": "warranty.claim",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_coverage_id": self.id,
                "default_product_id": self.product_id.id,
                "default_lot_id": self.lot_id.id,
                "default_partner_id": self.partner_id.id,
            },
        }

    @api.model
    def _cron_warranty_expiry_check(self):
        today = fields.Date.context_today(self)
        active_coverages = self.search([("state", "in", ("active", "claimed"))])
        for coverage in active_coverages:
            reminder_start = coverage.expiry_date - relativedelta(days=coverage.policy_id.reminder_days or 0)
            if (
                not coverage.pre_expiry_notified
                and coverage.policy_id.reminder_days >= 0
                and today >= reminder_start
                and today < coverage.expiry_date
            ):
                coverage._notify_pre_expiry()
            if today >= coverage.expiry_date:
                coverage._notify_expiry()
                coverage._set_state("expired")
                coverage._log_history("expired", _("Warranty expired automatically via scheduled action."))
        return True


