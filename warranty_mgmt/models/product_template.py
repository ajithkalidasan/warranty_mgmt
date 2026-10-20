from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    warranty_enabled = fields.Boolean(
        string="Warranty Available",
        help="Enable warranty handling for this product.",
    )
    warranty_policy_id = fields.Many2one(
        "warranty.policy",
        string="Warranty Policy",
        domain="[('active', '=', True)]",
        help="If set, this policy is preferred over the generic policy matching rules.",
    )
    warranty_creation_mode = fields.Selection(
        [
            ("policy", "Use Policy Setting"),
            ("manual", "Manual"),
            ("automatic", "Automatic"),
        ],
        string="Warranty Registration",
        default="policy",
        required=True,
        help="Choose whether this product follows the selected policy's Automatic Creation setting, always registers manually, or creates coverage automatically.",
    )
    warranty_type_id = fields.Many2one(
        "warranty.type",
        string="Warranty Type",
        related="warranty_policy_id.warranty_type_id",
        readonly=True,
        store=True,
    )
    warranty_duration = fields.Integer(
        string="Warranty Duration",
        related="warranty_policy_id.duration",
        readonly=True,
    )
    warranty_duration_unit = fields.Selection(
        related="warranty_policy_id.duration_unit",
        readonly=True,
    )
    warranty_start_from = fields.Selection(
        related="warranty_policy_id.start_from",
        readonly=True,
    )
    warranty_grace_days = fields.Integer(
        string="Grace Days",
        related="warranty_policy_id.grace_days",
        readonly=True,
    )
    warranty_reminder_days = fields.Integer(
        string="Reminder Days",
        related="warranty_policy_id.reminder_days",
        readonly=True,
    )
    warranty_covered_items = fields.Text(
        string="Covered Items",
        related="warranty_policy_id.covered_items",
        readonly=True,
    )
    warranty_exclusion_items = fields.Text(
        string="Exclusions",
        related="warranty_policy_id.exclusion_items",
        readonly=True,
    )

    @api.constrains("warranty_enabled", "warranty_policy_id")
    def _check_product_warranty_setup(self):
        for template in self:
            if template.warranty_policy_id and not template.warranty_enabled:
                raise ValidationError(
                    _("Enable Warranty Available before assigning a product-specific warranty policy.")
                )
