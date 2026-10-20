from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Documents a warranty can be given from, mapped to the origin stored on the
# coverage. Refunds are excluded on purpose: a refunded line is not a sale.
WARRANTY_ORIGIN_BY_MOVE_TYPE = {
    "out_invoice": "sale",
    "in_invoice": "purchase",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    warranty_coverage_ids = fields.One2many(
        "warranty.coverage",
        "account_move_id",
        string="Warranties",
        copy=False,
    )
    warranty_coverage_count = fields.Integer(
        compute="_compute_warranty_coverage_count",
    )
    warranty_can_give = fields.Boolean(
        compute="_compute_warranty_can_give",
        help="Technical field driving the Give Warranty button: true when this "
             "document still has a line that could be covered.",
    )

    @api.depends("warranty_coverage_ids")
    def _compute_warranty_coverage_count(self):
        # sudo: accountants without a warranty group still open invoices, and the
        # record rule on coverage limits a warranty user to their own records --
        # neither should change the count shown on the document.
        counts = dict(
            self.env["warranty.coverage"].sudo()._read_group(
                [("account_move_id", "in", self.ids)],
                groupby=["account_move_id"],
                aggregates=["__count"],
            )
        )
        for move in self:
            move.warranty_coverage_count = counts.get(move, 0)

    @api.depends("state", "move_type", "invoice_line_ids.product_id", "warranty_coverage_ids")
    def _compute_warranty_can_give(self):
        for move in self:
            move.warranty_can_give = bool(
                move.state == "posted"
                and move.move_type in WARRANTY_ORIGIN_BY_MOVE_TYPE
                and not move._get_warranty_blocking_reason()
                and move._get_warrantable_lines()
            )

    def _get_warranty_origin(self):
        """Origin stamped on every coverage created from this document."""
        self.ensure_one()
        return WARRANTY_ORIGIN_BY_MOVE_TYPE.get(self.move_type, "other")

    def _get_warranty_blocking_reason(self):
        """Why this document cannot hand out warranties, or an empty string.

        Extension point for connectors: a document whose warranties are granted
        somewhere else -- a repair invoiced through a helpdesk ticket, say --
        returns a message here so the wizard never offers to create a second,
        competing warranty for the same goods.
        """
        self.ensure_one()
        return ""

    def _get_warrantable_lines(self):
        """Invoice lines that could still be given a warranty.

        Only physical goods qualify: services, sections and notes are skipped.
        Two things are filtered out so the same goods are never covered twice:

        - lines that already carry a warranty of their own;
        - lines whose product is covered by a warranty that is attached to this
          document without naming a line -- a repair warranty granted on the
          ticket and carried over to the invoice, typically. Line-level
          warranties are deliberately not matched by product, so an invoice
          listing the same product on two lines can still cover both.
        """
        self.ensure_one()
        lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
            and line.product_id
            and line.product_id.type == "consu"
        )
        if not lines:
            return lines
        # sudo: the record rule limits a warranty user to their own coverages, but
        # a warranty granted by a colleague must still block a second one here.
        coverage_model = self.env["warranty.coverage"].sudo()
        live_states = ("draft", "active", "claimed")
        covered_lines = coverage_model.search(
            [("account_move_line_id", "in", lines.ids), ("state", "in", live_states)]
        ).account_move_line_id
        covered_products = coverage_model.search(
            [
                ("account_move_id", "=", self.id),
                ("account_move_line_id", "=", False),
                ("state", "in", live_states),
            ]
        ).product_id
        return (lines - covered_lines).filtered(
            lambda line: line.product_id not in covered_products
        )

    def _get_warranty_line_lot(self, line):
        """Best-effort serial for an invoice line.

        Only returned when the delivery behind the line moved exactly one lot:
        guessing on a multi-serial line would attach the warranty to the wrong
        device. The user can always pick the serial in the wizard.
        """
        self.ensure_one()
        empty = self.env["stock.lot"]
        if "sale_line_ids" not in line._fields:
            sale_lines = empty
        else:
            sale_lines = line.sale_line_ids
        if not sale_lines or "move_ids" not in sale_lines._fields:
            purchase_lines = line.purchase_line_id if "purchase_line_id" in line._fields else self.env["purchase.order.line"]
            if not purchase_lines or "move_ids" not in purchase_lines._fields:
                return empty
            lots = purchase_lines.move_ids.filtered(lambda move: move.state == "done").lot_ids
            return lots if len(lots) == 1 else empty
        lots = sale_lines.move_ids.filtered(lambda move: move.state == "done").lot_ids
        return lots if len(lots) == 1 else empty

    def _get_warranty_start_date(self):
        self.ensure_one()
        return self.invoice_date or fields.Date.context_today(self)

    def action_open_warranty_wizard(self):
        self.ensure_one()
        if self.move_type not in WARRANTY_ORIGIN_BY_MOVE_TYPE:
            raise UserError(_(
                "Warranties can only be given from a customer invoice or a vendor bill."
            ))
        if self.state != "posted":
            raise UserError(_("Post the document before giving a warranty."))
        blocking_reason = self._get_warranty_blocking_reason()
        if blocking_reason:
            raise UserError(blocking_reason)
        if not self._get_warrantable_lines():
            raise UserError(_(
                "Every product on this document already has a warranty, or there are "
                "no physical goods to cover."
            ))
        return {
            "type": "ir.actions.act_window",
            "name": _("Register Supplier Warranty") if self.move_type == "in_invoice" else _("Give Customer Warranty"),
            "res_model": "account.warranty.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_move_id": self.id},
        }

    def action_give_customer_warranty(self):
        self.ensure_one()
        if self.move_type != "out_invoice":
            raise UserError(_("Customer warranties can only be registered from customer invoices."))
        return self.action_open_warranty_wizard()

    def action_register_supplier_warranty(self):
        self.ensure_one()
        if self.move_type != "in_invoice":
            raise UserError(_("Supplier warranties can only be registered from vendor bills."))
        return self.action_open_warranty_wizard()

    def action_view_warranty_coverages(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": _("Warranties"),
            "res_model": "warranty.coverage",
            "view_mode": "list,form",
            "domain": [("account_move_id", "=", self.id)],
            "context": {"default_account_move_id": self.id},
        }
        if self.warranty_coverage_count == 1:
            action.update({
                "view_mode": "form",
                "res_id": self.warranty_coverage_ids.id,
            })
        return action
