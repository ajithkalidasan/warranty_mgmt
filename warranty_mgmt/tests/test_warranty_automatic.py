from unittest.mock import patch

from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class TestWarrantyAutomaticCreation(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warranty_type = cls.env["warranty.type"].sudo().create({
            "name": "Automatic Creation Test",
            "code": "AUTO_CREATION_TEST",
        })
        cls.policy = cls.env["warranty.policy"].sudo().create({
            "name": "Automatic Creation Policy",
            "warranty_type_id": cls.warranty_type.id,
            "duration": 12,
            "duration_unit": "month",
            "apply_on": "all",
            "start_from": "source_date",
        })

    def _configure_product(self, mode="policy", automatic=True, assign_policy=True):
        template = self.product_a.product_tmpl_id
        template.write({
            "warranty_enabled": True,
            "warranty_policy_id": self.policy.id if assign_policy else False,
            "warranty_creation_mode": mode,
        })
        self.policy.auto_create = automatic

    def _posted_move(self, move_type="out_invoice"):
        return self._create_invoice_one_line(
            move_type=move_type,
            product_id=self.product_a,
            post=True,
            invoice_date=fields.Date.today(),
        )

    def test_policy_setting_creates_customer_coverage_on_post(self):
        self._configure_product(mode="policy", automatic=True)
        move = self._posted_move()
        coverages = self.env["warranty.coverage"].sudo().search([
            ("account_move_id", "=", move.id)
        ])
        self.assertEqual(len(coverages), 1)
        self.assertEqual(coverages.warranty_origin, "sale")
        self.assertEqual(coverages.policy_id, self.policy)
        self.assertEqual(coverages.start_date, move.invoice_date)

    def test_policy_setting_creates_supplier_coverage_on_post(self):
        self._configure_product(mode="policy", automatic=True)
        move = self._posted_move("in_invoice")
        self.assertEqual(move.warranty_coverage_ids.warranty_origin, "purchase")

    def test_product_manual_override_keeps_manual_flow(self):
        self._configure_product(mode="manual", automatic=True)
        move = self._posted_move()
        self.assertFalse(move.warranty_coverage_ids)
        self.assertTrue(move.warranty_can_give)

    def test_product_automatic_override_enables_manual_policy(self):
        self._configure_product(mode="automatic", automatic=False)
        move = self._posted_move()
        self.assertEqual(len(move.warranty_coverage_ids), 1)

    def test_unavailable_policy_date_is_reported(self):
        self._configure_product(mode="automatic", automatic=True)
        self.policy.start_from = "manual"
        move = self._posted_move()
        self.assertFalse(move.warranty_coverage_ids)
        self.assertTrue(any("no date available" in message.body for message in move.message_ids))

    def test_coverage_creation_is_idempotent_and_per_lot(self):
        self._configure_product(mode="automatic", automatic=True)
        move = self._create_invoice_one_line(
            move_type="out_invoice", product_id=self.product_a, post=False,
            invoice_date=fields.Date.today(),
        )
        lots = self.env["stock.lot"].create([
            {"name": "AUTO-CREATE-LOT-1", "product_id": self.product_a.id, "company_id": self.env.company.id},
            {"name": "AUTO-CREATE-LOT-2", "product_id": self.product_a.id, "company_id": self.env.company.id},
        ])
        with patch.object(type(move), "_get_warranty_line_lots", return_value=lots):
            move.action_post()
            coverage_model = self.env["warranty.coverage"].sudo()
            coverage = coverage_model.search([("account_move_id", "=", move.id)])
            self.assertEqual(len(coverage), 2)
            self.assertEqual(set(coverage.mapped("lot_id").ids), set(lots.ids))
            move._create_automatic_warranties()
            self.assertEqual(coverage_model.search_count([("account_move_id", "=", move.id)]), 2)

