from odoo import fields, models


class WarrantyType(models.Model):
    _name = "warranty.type"
    _description = "Warranty Type"
    _order = "name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    description = fields.Text()
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "The warranty type code must be unique.",
    )

