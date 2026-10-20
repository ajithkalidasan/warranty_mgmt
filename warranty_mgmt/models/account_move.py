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

    @api.depends(
        "state", "move_type", "invoice_line_ids.product_id", "warranty_coverage_ids",
        "invoice_line_ids.purchase_line_id.move_ids.state",
        "invoice_line_ids.purchase_line_id.move_ids.move_line_ids.lot_id",
    )
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
        coverages = coverage_model.search(
            [("account_move_line_id", "in", lines.ids), ("state", "in", live_states)]
        )
        covered_without_lot_lines = coverages.filtered(lambda coverage: not coverage.lot_id).account_move_line_id
        covered_products = coverage_model.search(
            [
                ("account_move_id", "=", self.id),
                ("account_move_line_id", "=", False),
                ("state", "in", live_states),
            ]
        ).product_id
        lines -= covered_without_lot_lines
        lines = lines.filtered(lambda line: line.product_id not in covered_products)
        return lines.filtered(lambda line: (
            bool(self._get_uncovered_warranty_lots(line))
            if self._get_warranty_line_lots(line)
            else not coverage_model.search_count([
                ("account_move_line_id", "=", line.id), ("state", "in", live_states)
            ])
        ))

    def _get_uncovered_warranty_lots(self, line):
        self.ensure_one()
        lots = self._get_warranty_line_lots(line)
        if not lots:
            return lots
        coverages = self.env["warranty.coverage"].sudo().search([
            ("lot_id", "in", lots.ids),
            ("warranty_origin", "=", self._get_warranty_origin()),
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("draft", "active", "claimed")),
        ])
        return lots - coverages.lot_id

    def _get_warranty_line_lot(self, line):
        """Best-effort serial for an invoice line.

        Only returned when the delivery behind the line moved exactly one lot:
        guessing on a multi-serial line would attach the warranty to the wrong
        device. The user can always pick the serial in the wizard.
        """
        self.ensure_one()
        lots = self._get_warranty_line_lots(line)
        return lots if len(lots) == 1 else self.env["stock.lot"]

    def _get_warranty_line_lots(self, line):
        self.ensure_one()
        return self._get_warranty_line_stock_moves(line).lot_ids

    def _get_warranty_line_stock_moves(self, line):
        self.ensure_one()
        moves = self.env["stock.move"]
        if "sale_line_ids" in line._fields and line.sale_line_ids:
            moves = line.sale_line_ids.move_ids
        elif "purchase_line_id" in line._fields and line.purchase_line_id:
            moves = line.purchase_line_id.move_ids
        return moves.filtered(lambda move: move.state == "done")

    def _get_warranty_line_receipt_date(self, line, lot=False):
        self.ensure_one()
        moves = self._get_warranty_line_stock_moves(line)
        if lot:
            moves = moves.filtered(lambda move: any(
                move_line.lot_id == lot for move_line in move.move_line_ids
            ))
        dates = []
        for move in moves:
            date_value = move.picking_id.date_done or move.date
            if date_value:
                dates.append(fields.Datetime.to_datetime(date_value).date())
        return max(dates) if dates else False

    def _get_warranty_start_date(self):
        self.ensure_one()
        return self.invoice_date or fields.Date.context_today(self)

    def _get_automatic_warranty_policy(self, product):
        self.ensure_one()
        template = product.product_tmpl_id.sudo()
        Policy = self.env["warranty.policy"].sudo()
        if not template.warranty_enabled or template.warranty_creation_mode == "manual":
            return Policy
        if template.warranty_policy_id and template.warranty_policy_id.active:
            policy = template.warranty_policy_id
            if policy.is_product_applicable(product) and (
                template.warranty_creation_mode == "automatic" or policy.auto_create
            ):
                return policy
            return Policy
        return self.env["warranty.coverage"].sudo()._find_matching_policy(product)

    def _get_automatic_warranty_start_date(self, line, policy, lot=False):
        self.ensure_one()
        if policy.start_from == "source_date":
            return self.invoice_date or self.date
        if policy.start_from == "today":
            return fields.Date.context_today(self)
        if policy.start_from == "receipt_date":
            return self._get_warranty_line_receipt_date(line, lot=lot)
        return False

    def _create_automatic_warranties(self):
        Coverage = self.env["warranty.coverage"].sudo()
        created = Coverage
        skipped = []
        lines = self.invoice_line_ids.filtered(lambda line:
            line.display_type == "product"
            and line.product_id
            and line.product_id.type == "consu"
        )
        for line in lines:
            template = line.product_id.product_tmpl_id.sudo()
            if not template.warranty_enabled or template.warranty_creation_mode == "manual":
                continue
            policy = self._get_automatic_warranty_policy(line.product_id)
            if not policy:
                skipped.append(_("%(product)s: no active matching automatic policy", product=line.product_id.display_name))
                continue
            lots = self._get_warranty_line_lots(line)
            targets = list(lots) if lots else [self.env["stock.lot"]]
            for lot in targets:
                start_date = self._get_automatic_warranty_start_date(line, policy, lot=lot)
                if not start_date:
                    rule = dict(policy._fields["start_from"].selection).get(policy.start_from, policy.start_from)
                    skipped.append(_("%(product)s: no date available for %(rule)s", product=line.product_id.display_name, rule=rule))
                    continue
                if lot:
                    duplicate = Coverage.search_count([
                        ("lot_id", "=", lot.id),
                        ("warranty_origin", "=", self._get_warranty_origin()),
                        ("company_id", "=", self.company_id.id),
                        ("state", "in", ("draft", "active", "claimed")),
                    ])
                else:
                    duplicate = Coverage.search_count([
                        ("account_move_line_id", "=", line.id),
                        ("lot_id", "=", False),
                        ("state", "in", ("draft", "active", "claimed")),
                    ])
                if duplicate:
                    skipped.append(_("%(product)s: duplicate coverage for %(lot)s", product=line.product_id.display_name, lot=lot.name if lot else _("the invoice line")))
                    continue
                vals = {
                    "product_id": line.product_id.id,
                    "partner_id": self.partner_id.id,
                    "policy_id": policy.id,
                    "start_date": start_date,
                    "expiry_date": Coverage._compute_expiry(start_date, policy),
                    "state": "active",
                    "warranty_origin": self._get_warranty_origin(),
                    "source_model": self._name,
                    "source_id": self.id,
                    "source_ref": self.name,
                    "account_move_id": self.id,
                    "account_move_line_id": line.id,
                    "company_id": self.company_id.id,
                }
                if lot:
                    vals["lot_id"] = lot.id
                try:
                    with self.env.cr.savepoint():
                        new_coverage = Coverage.create_warranty(vals)
                    created |= new_coverage
                except Exception as error:
                    skipped.append(_("%(product)s / %(lot)s: %(error)s", product=line.product_id.display_name, lot=lot.name if lot else _("no lot"), error=str(error)))
        if created or skipped:
            messages = []
            if created:
                messages.append(_("Automatically created %(count)s warranty record(s): %(names)s", count=len(created), names=", ".join(created.mapped("display_name"))))
            if skipped:
                messages.append(_("Not created: %(reasons)s", reasons="; ".join(skipped)))
            self.message_post(body="<br/>".join(messages))
        return created

    def action_post(self):
        result = super().action_post()
        for move in self.filtered(lambda item:
            item.state == "posted" and item.move_type in WARRANTY_ORIGIN_BY_MOVE_TYPE
        ):
            move._create_automatic_warranties()
        return result

    def button_draft(self):
        result = super().button_draft()
        for move in self.filtered(lambda item: self.env["warranty.coverage"].sudo().search_count([
            ("account_move_id", "=", item.id)
        ])):
            move.message_post(body=_(
                "This source document was reset to draft. Linked warranty coverage was retained; review and void it if appropriate."
            ))
        return result

    def button_cancel(self):
        result = super().button_cancel()
        for move in self.filtered(lambda item: item.state == "cancel" and self.env["warranty.coverage"].sudo().search_count([
            ("account_move_id", "=", item.id)
        ])):
            move.message_post(body=_(
                "This source document was canceled. Linked warranty coverage was retained; review and void it if appropriate."
            ))
        return result

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
