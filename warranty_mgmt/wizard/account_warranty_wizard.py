from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DURATION_UNITS = [
    ("day", "Days"),
    ("week", "Weeks"),
    ("month", "Months"),
    ("year", "Years"),
]


class AccountWarrantyWizard(models.TransientModel):
    _name = "account.warranty.wizard"
    _description = "Give Warranty From Invoice"

    move_id = fields.Many2one(
        "account.move",
        string="Invoice",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    move_type = fields.Selection(related="move_id.move_type")
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        related="move_id.partner_id",
        readonly=True,
    )
    warranty_origin = fields.Selection(
        selection=lambda self: self.env["warranty.coverage"]
        ._fields["warranty_origin"]
        ._description_selection(self.env),
        string="Origin",
        compute="_compute_warranty_origin",
        help="Sale warranties come from customer invoices, vendor warranties from "
             "vendor bills. Repair warranties are granted on the ticket instead, so "
             "the two can never be confused for the same goods.",
    )
    start_date = fields.Date(
        string="Warranty Start Date",
        required=True,
        help="Defaults to the invoice date. Applied to every line that does not "
             "carry its own start date.",
    )
    line_ids = fields.One2many(
        "account.warranty.wizard.line",
        "wizard_id",
        string="Products",
    )

    @api.depends("move_id")
    def _compute_warranty_origin(self):
        for wizard in self:
            wizard.warranty_origin = wizard.move_id._get_warranty_origin() if wizard.move_id else False

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        move_id = values.get("move_id") or self.env.context.get("default_move_id")
        if not move_id:
            return values
        move = self.env["account.move"].browse(move_id)
        if "start_date" in fields_list and not values.get("start_date"):
            values["start_date"] = move._get_warranty_start_date()
        # Policy is deliberately left empty: the user chooses the warranty for
        # each product, rather than inheriting whatever the product is configured
        # with.
        if "line_ids" in fields_list:
            wizard_lines = []
            for invoice_line in move._get_warrantable_lines():
                available_lots = move._get_uncovered_warranty_lots(invoice_line)
                wizard_lines.append((0, 0, {
                    "invoice_line_id": invoice_line.id,
                    "product_id": invoice_line.product_id.id,
                    "lot_id": available_lots.id if len(available_lots) == 1 else False,
                }))
            values["line_ids"] = wizard_lines
        return values

    def action_confirm(self):
        self.ensure_one()
        if self.move_id.state != "posted" or self.move_id.move_type not in ("out_invoice", "in_invoice"):
            raise UserError(_("Only posted customer invoices and vendor bills can grant warranties."))
        selected = self.line_ids.filtered("selected")
        if not selected:
            raise UserError(_("Select at least one product to give a warranty for."))
        selected._check_ready()
        eligible_lines = self.move_id._get_warrantable_lines()
        invalid = selected.filtered(lambda line: not line.invoice_line_id or line.invoice_line_id not in eligible_lines)
        if invalid:
            raise UserError(_("Some selected products are no longer eligible for a warranty. Refresh the document and try again."))

        coverage_model = self.env["warranty.coverage"]
        created = coverage_model
        for line in selected:
            created |= coverage_model.create_warranty(line._prepare_coverage_vals())

        self.move_id.message_post(
            body=_(
                "%(count)s warranty record(s) created: %(names)s",
                count=len(created),
                names=", ".join(created.mapped("display_name")),
            )
        )
        if len(created) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "warranty.coverage",
                "view_mode": "form",
                "res_id": created.id,
            }
        return self.move_id.action_view_warranty_coverages()


class AccountWarrantyWizardLine(models.TransientModel):
    _name = "account.warranty.wizard.line"
    _description = "Give Warranty From Invoice Line"

    wizard_id = fields.Many2one(
        "account.warranty.wizard",
        required=True,
        ondelete="cascade",
        index=True,
    )
    selected = fields.Boolean(string="Give", default=True)
    invoice_line_id = fields.Many2one("account.move.line", string="Invoice Line", readonly=True)
    product_id = fields.Many2one("product.product", string="Product", required=True)
    lot_id = fields.Many2one(
        "stock.lot",
        string="Serial / Lot",
        domain="[('product_id', '=', product_id)]",
    )
    policy_id = fields.Many2one(
        "warranty.policy",
        string="Warranty",
        domain="[('active', '=', True)]",
        help="Chosen per product. The duration below is filled from this policy "
             "but can be changed for this invoice without affecting the policy.",
    )
    duration = fields.Integer(
        string="Duration",
        compute="_compute_duration",
        store=True,
        readonly=False,
        help="Overrides the policy duration for this invoice only. The policy "
             "itself is not modified.",
    )
    duration_unit = fields.Selection(
        DURATION_UNITS,
        string="Unit",
        compute="_compute_duration",
        store=True,
        readonly=False,
    )
    start_date = fields.Date(
        string="From",
        compute="_compute_start_date",
        store=True,
        readonly=False,
    )
    expiry_date = fields.Date(
        string="To",
        compute="_compute_expiry_date",
        store=True,
        readonly=False,
        help="Recomputed from the start date and duration. Edit it directly to "
             "set an exact end date.",
    )

    @api.depends("policy_id")
    def _compute_duration(self):
        """Seed the duration from the chosen policy, leaving it editable."""
        for line in self:
            if line.policy_id:
                line.duration = line.policy_id.duration
                line.duration_unit = line.policy_id.duration_unit
            else:
                line.duration = 0
                line.duration_unit = "month"

    @api.depends("wizard_id.start_date")
    def _compute_start_date(self):
        for line in self:
            line.start_date = line.wizard_id.start_date

    @api.depends("start_date", "duration", "duration_unit")
    def _compute_expiry_date(self):
        for line in self:
            line.expiry_date = line._get_expiry_date()

    def _get_expiry_date(self):
        self.ensure_one()
        if not self.start_date or self.duration <= 0 or not self.duration_unit:
            return False
        delta = {
            "day": relativedelta(days=self.duration),
            "week": relativedelta(weeks=self.duration),
            "month": relativedelta(months=self.duration),
            "year": relativedelta(years=self.duration),
        }[self.duration_unit]
        return self.start_date + delta

    def _check_ready(self):
        """Validate the picked lines before any warranty is created.

        Deliberately not an @api.constrains: these run on flush, before
        action_confirm, and a line still missing its policy would trip the
        duration check first and report a confusing message.
        """
        missing_policy = self.filtered(lambda line: not line.policy_id)
        if missing_policy:
            raise UserError(_(
                "Choose a warranty for: %s",
                ", ".join(missing_policy.mapped("product_id.display_name")),
            ))
        for line in self:
            label = line.product_id.display_name
            if not line.policy_id.active or not line.policy_id.is_product_applicable(line.product_id):
                raise UserError(_("The selected warranty is inactive or does not apply to %s.", label))
            if line.invoice_line_id and line.invoice_line_id.product_id != line.product_id:
                raise UserError(_("The product on %s no longer matches its invoice line.", label))
            if line.lot_id and line.lot_id.product_id != line.product_id:
                raise UserError(_("The selected serial or lot does not match %s.", label))
            existing_domain = [
                ("warranty_origin", "=", line.wizard_id.move_id._get_warranty_origin()),
                ("company_id", "=", line.wizard_id.move_id.company_id.id),
                ("state", "in", ("draft", "active", "claimed")),
            ]
            if line.lot_id:
                existing_domain.append(("lot_id", "=", line.lot_id.id))
            elif line.invoice_line_id:
                existing_domain += [
                    ("account_move_line_id", "=", line.invoice_line_id.id),
                    ("lot_id", "=", False),
                ]
            if self.env["warranty.coverage"].sudo().search_count(existing_domain):
                raise UserError(_("This product or lot already has current warranty coverage."))
            if line.duration <= 0:
                raise UserError(_("The duration for %s must be greater than zero.", label))
            if not line.start_date or not line.expiry_date:
                raise UserError(_("Set a start and expiry date for %s.", label))
            if line.expiry_date <= line.start_date:
                raise UserError(
                    _("The expiry date for %s must be later than its start date.", label)
                )

    def _prepare_coverage_vals(self):
        self.ensure_one()
        move = self.wizard_id.move_id
        vals = {
            "product_id": self.product_id.id,
            "partner_id": move.partner_id.id,
            "policy_id": self.policy_id.id,
            "start_date": self.start_date,
            # Passed explicitly so the per-invoice override wins over the duration
            # stored on the policy.
            "expiry_date": self.expiry_date,
            "state": "active",
            "warranty_origin": move._get_warranty_origin(),
            "source_model": move._name,
            "source_id": move.id,
            "source_ref": move.name,
            "account_move_id": move.id,
            "company_id": move.company_id.id,
        }
        if self.lot_id:
            vals["lot_id"] = self.lot_id.id
        if self.invoice_line_id:
            vals["account_move_line_id"] = self.invoice_line_id.id
        return vals
