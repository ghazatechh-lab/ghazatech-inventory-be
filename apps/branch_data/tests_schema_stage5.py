from django.test import SimpleTestCase, override_settings
from unittest.mock import patch
from apps.branch_data.schema_routing import branch_alias

class BranchSchemaNamingTests(SimpleTestCase):
    def test_vat(self):
        self.assertEqual(branch_alias(19, "VAT"), ("vat", "branch_00000019"))

    def test_non_vat(self):
        self.assertEqual(branch_alias(20, "NON_VAT"), ("non_vat", "branch_00000020"))

    def test_invalid_tax_mode(self):
        with self.assertRaises(ValueError):
            branch_alias(1, "MASTER")
