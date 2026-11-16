"""Regression tests: assigning locations never changes physical stock."""
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from apps.inventory.rack_ops import validate_rack_quantity


class RackQuantityGuardTests(SimpleTestCase):
    def test_full_existing_inventory_can_be_allocated(self):
        self.assertEqual(validate_rack_quantity(89, 0, 89), 0)

    def test_repeating_absolute_quantity_is_idempotent(self):
        self.assertEqual(validate_rack_quantity(89, 0, 89), 0)
        self.assertEqual(validate_rack_quantity(89, 0, 89), 0)

    def test_other_rack_quantities_are_reserved(self):
        self.assertEqual(validate_rack_quantity(49, 40, 89), 0)

    def test_cannot_allocate_more_than_physical_stock(self):
        with self.assertRaises(ValidationError):
            validate_rack_quantity(90, 0, 89)
        with self.assertRaises(ValidationError):
            validate_rack_quantity(50, 40, 89)

    def test_reject_negative_quantities(self):
        with self.assertRaises(ValidationError):
            validate_rack_quantity(-1, 0, 89)
