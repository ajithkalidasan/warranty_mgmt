from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyPolicy(models.Model):
    _name = "warranty.policy"
    _description = "Warranty Policy"
    _order = "name"

    name = fields.Char(required=True, index=True)
    warranty_type_id = fields.Many2one(
        "warranty.type",
        string="Warranty Type",
        required=True,
        ondelete="restrict",
        index=True,
    )
    duration = fields.Integer(required=True, default=12)
    duration_unit = fields.Selection(
        [
            ("day", "Days"),
            ("week", "Weeks"),
            ("month", "Months"),
            ("year", "Years"),
        ],
        required=True,
        default="month",
    )
    start_from = fields.Selection(
        [
            ("manual", "Manual Start"),
            ("receipt_date", "Receipt Date"),
            ("qc_pass_date", "QC Pass Date"),
            ("source_date", "Source Date"),
            ("today", "Current Date"),
        ],
        required=True,
        default="manual",
        help="Automatic creation uses the source document date, current date, or completed delivery/receipt date when selected. Manual and QC dates need an available date source; otherwise the line is skipped and reported.",
    )
    apply_on = fields.Selection(
        [
            ("all", "All Products"),
            ("product", "Selected Products"),
            ("category", "Selected Categories"),
        ],
        required=True,
        default="all",
    )
    auto_create = fields.Boolean(
        string="Automatic Creation",
        help="Automatically create coverage when a matching customer invoice or vendor bill is posted. A product can inherit or override this setting.",
    )
    grace_days = fields.Integer(default=0)
    reminder_days = fields.Integer(
        default=15,
        help="Number of days before expiry to trigger pre-expiry notifications.",
    )
    max_claims = fields.Integer(default=1)
    allow_multiple_claims = fields.Boolean(default=False)
    product_ids = fields.Many2many(
        "product.product",
        "warranty_policy_product_rel",
        "policy_id",
        "product_id",
        string="Products",
    )
    category_ids = fields.Many2many(
        "product.category",
        "warranty_policy_category_rel",
        "policy_id",
        "category_id",
        string="Product Categories",
    )
    covered_items = fields.Text()
    exclusion_items = fields.Text()
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique(name)",
        "The warranty policy name must be unique.",
    )

    @api.constrains("duration", "grace_days", "reminder_days", "max_claims", "allow_multiple_claims")
    def _check_policy_values(self):
        for policy in self:
            if policy.duration <= 0:
                raise ValidationError(_("Warranty duration must be greater than zero."))
            if policy.grace_days < 0:
                raise ValidationError(_("Grace days cannot be negative."))
            if policy.reminder_days < 0:
                raise ValidationError(_("Reminder days cannot be negative."))
            if policy.max_claims <= 0:
                raise ValidationError(_("Maximum claims must be greater than zero."))
            if not policy.allow_multiple_claims and policy.max_claims != 1:
                raise ValidationError(
                    _("Policies that do not allow multiple claims must have a maximum claim count of 1.")
                )

    @api.constrains("apply_on", "product_ids", "category_ids")
    def _check_scope_configuration(self):
        for policy in self:
            if policy.apply_on == "product" and not policy.product_ids:
                raise ValidationError(_("Add at least one product when the policy applies on selected products."))
            if policy.apply_on == "category" and not policy.category_ids:
                raise ValidationError(
                    _("Add at least one product category when the policy applies on selected categories."))

    def is_product_applicable(self, product):
        self.ensure_one()
        if not product:
            return False
        if self.apply_on == "all":
            return True
        if self.apply_on == "product":
            return product in self.product_ids
        return product.categ_id in self.category_ids

