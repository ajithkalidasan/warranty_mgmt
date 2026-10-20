from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyCoverage(models.Model):
    _inherit = "warranty.coverage"

    account_move_id = fields.Many2one(
        "account.move", string="Invoice / Bill", copy=False, readonly=True,
        index=True, ondelete="set null", check_company=True,
    )
    account_move_line_id = fields.Many2one(
        "account.move.line", string="Invoice Line", copy=False, readonly=True,
        index=True, ondelete="set null", check_company=True,
    )
    purchase_order_id = fields.Many2one(
        "purchase.order", string="Purchase Order", copy=False, readonly=True,
        index=True, ondelete="set null", check_company=True,
    )
    purchase_order_line_id = fields.Many2one(
        "purchase.order.line", string="Purchase Order Line", copy=False,
        readonly=True, index=True, ondelete="set null", check_company=True,
    )

    @api.constrains("warranty_origin", "account_move_id", "account_move_line_id", "purchase_order_id", "purchase_order_line_id")
    def _check_source_links(self):
        for coverage in self:
            if coverage.account_move_id:
                expected = "sale" if coverage.account_move_id.move_type == "out_invoice" else (
                    "purchase" if coverage.account_move_id.move_type == "in_invoice" else False
                )
                if expected != coverage.warranty_origin:
                    raise ValidationError(_("Warranty origin must match the linked invoice or vendor bill."))
            if coverage.account_move_line_id and coverage.account_move_id != coverage.account_move_line_id.move_id:
                raise ValidationError(_("The invoice line must belong to the linked invoice or bill."))
            if coverage.purchase_order_line_id and coverage.purchase_order_id != coverage.purchase_order_line_id.order_id:
                raise ValidationError(_("The purchase line must belong to the linked purchase order."))
            if coverage.purchase_order_line_id and coverage.warranty_origin != "purchase":
                raise ValidationError(_("Purchase order lines can only be linked to supplier warranties."))

    @api.constrains("account_move_line_id", "purchase_order_line_id", "warranty_origin", "state")
    def _check_duplicate_source_line_warranty(self):
        blocking_states = ("draft", "active", "claimed")
        for coverage in self.filtered(lambda item: item.state in blocking_states):
            checks = []
            if coverage.account_move_line_id:
                checks.append(("account_move_line_id", coverage.account_move_line_id.id))
            if coverage.purchase_order_line_id:
                checks.append(("purchase_order_line_id", coverage.purchase_order_line_id.id))
            for field_name, value in checks:
                lock_key = "%s:%s:%s" % (coverage.warranty_origin, field_name, value)
                self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [lock_key])
                duplicate = self.sudo().search_count([
                    ("id", "!=", coverage.id),
                    (field_name, "=", value),
                    ("warranty_origin", "=", coverage.warranty_origin),
                    ("state", "in", blocking_states),
                ])
                if duplicate:
                    raise ValidationError(_(
                        "This source line already has a current warranty of the same origin."
                    ))
