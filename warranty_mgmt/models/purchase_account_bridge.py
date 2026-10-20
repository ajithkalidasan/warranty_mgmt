from odoo import api, models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _get_warrantable_lines(self):
        lines = super()._get_warrantable_lines()
        if self.move_type != "in_invoice" or not lines:
            return lines
        purchase_lines = lines.purchase_line_id
        if not purchase_lines:
            return lines
        covered = self.env["warranty.coverage"].sudo().search([
            ("purchase_order_line_id", "in", purchase_lines.ids),
            ("warranty_origin", "=", "purchase"),
            ("state", "in", ("draft", "active", "claimed")),
        ]).purchase_order_line_id
        return lines.filtered(lambda line: not line.purchase_line_id or line.purchase_line_id not in covered)


class AccountWarrantyWizardLine(models.TransientModel):
    _inherit = "account.warranty.wizard.line"

    def _prepare_coverage_vals(self):
        vals = super()._prepare_coverage_vals()
        purchase_line = self.invoice_line_id.purchase_line_id
        if purchase_line:
            vals.update({
                "purchase_order_id": purchase_line.order_id.id,
                "purchase_order_line_id": purchase_line.id,
            })
        return vals
