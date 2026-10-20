from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase


class TestWarrantyWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warranty_type = cls.env["warranty.type"].create({
            "name": "Workflow Test",
            "code": "WORKFLOW_TEST",
        })
        cls.policy = cls.env["warranty.policy"].create({
            "name": "Workflow Test Policy",
            "warranty_type_id": cls.warranty_type.id,
            "duration": 12,
            "duration_unit": "month",
            "apply_on": "all",
            "auto_create": True,
        })
        cls.product = cls.env["product.product"].create({"name": "Warranty Test Product"})
        cls.lot = cls.env["stock.lot"].create({
            "name": "WARRANTY-TEST-001",
            "product_id": cls.product.id,
            "company_id": cls.company.id,
        })

    def _create_coverage(self, origin):
        return self.env["warranty.coverage"].create_warranty({
            "product_id": self.product.id,
            "lot_id": self.lot.id,
            "policy_id": self.policy.id,
            "company_id": self.company.id,
            "warranty_origin": origin,
        })

    def test_customer_and_supplier_warranties_are_separate_origins(self):
        sale_coverage = self._create_coverage("sale")
        supplier_coverage = self._create_coverage("purchase")
        self.assertEqual(sale_coverage.state, "active")
        self.assertEqual(supplier_coverage.state, "active")
        self.assertNotEqual(sale_coverage.warranty_origin, supplier_coverage.warranty_origin)

    def test_duplicate_serial_is_blocked_within_same_origin(self):
        self._create_coverage("sale")
        with self.assertRaises(ValidationError):
            self._create_coverage("sale")

    def test_direct_state_write_is_rejected(self):
        coverage = self._create_coverage("sale")
        with self.assertRaises(UserError):
            coverage.write({"state": "void"})

    def test_history_is_append_only(self):
        coverage = self._create_coverage("sale")
        event = coverage.history_ids[:1]
        self.assertTrue(event)
        with self.assertRaises(AccessError):
            event.write({"note": "tampered"})
        with self.assertRaises(AccessError):
            event.unlink()
