from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .workflow import WORKFLOW_TOKEN


class WarrantyHistory(models.Model):
    _name = "warranty.history"
    _description = "Warranty History"
    _order = "event_date desc, id desc"

    coverage_id = fields.Many2one("warranty.coverage", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="coverage_id.company_id", store=True, readonly=True, index=True)
    event = fields.Char(required=True, index=True)
    note = fields.Text()
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, index=True)
    event_date = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("_warranty_internal_create") is not WORKFLOW_TOKEN:
            raise AccessError(_("Warranty history entries can only be added by warranty workflows."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Warranty history is append-only."))

    def unlink(self):
        raise AccessError(_("Warranty history is append-only."))
