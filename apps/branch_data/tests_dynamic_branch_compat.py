from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.branch_data.workforce_flow import is_physical, is_combined
from apps.branch_data.schema_routing import branch_alias


class DynamicBranchCompatibilityTests(SimpleTestCase):
    def test_physical_classification_does_not_depend_on_code(self):
        branch = SimpleNamespace(branch_code="DXB-WH", tax_mode="VAT", is_active=True)
        self.assertTrue(is_physical(branch))
        self.assertFalse(is_combined(branch))

    def test_consolidated_branch_does_not_require_br03(self):
        branch = SimpleNamespace(branch_code="CONSOLIDATED", tax_mode="", branch_type="MASTER", is_active=True)
        self.assertTrue(is_combined(branch))
        self.assertFalse(is_physical(branch))

    def test_dynamic_schema_name(self):
        self.assertEqual(branch_alias(3, "NON_VAT"), ("non_vat", "branch_00000003"))
