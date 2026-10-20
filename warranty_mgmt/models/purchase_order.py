from odoo import _, api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    warranty_coverage_ids = fields.One2many(
        "warranty.coverage",
        "purchase_order_id",
        string="Warranties",
        copy=False,
    )
    warranty_coverage_count = fields.Integer(
        compute="_compute_warranty_coverage_count",
    )

    @api.depends("warranty_coverage_ids")
    def _compute_warranty_coverage_count(self):
        # sudo: buyers without a warranty group still open purchase orders, and
        # the record rule on coverage limits a warranty user to their own records.
        counts = dict(
            self.env["warranty.coverage"].sudo()._read_group(
                [("purchase_order_id", "in", self.ids)],
                groupby=["purchase_order_id"],
                aggregates=["__count"],
            )
        )
        for order in self:
            order.warranty_coverage_count = counts.get(order, 0)

    def action_view_warranty_coverages(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": _("Warranties"),
            "res_model": "warranty.coverage",
            "view_mode": "list,form",
            "domain": [("purchase_order_id", "=", self.id)],
            "context": {"default_purchase_order_id": self.id},
        }
        if self.warranty_coverage_count == 1:
            action.update({
                "view_mode": "form",
                "res_id": self.warranty_coverage_ids.id,
            })
        return action
