"""Regression checks for rack allocation limits without requiring tenant fixtures."""
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from apps.inventory.rack_ops import validate_rack_quantity


class MultiRackAllocationContractTests(SimpleTestCase):
    def test_split_entire_existing_stock(self):
        self.assertEqual(validate_rack_quantity(10, 11, 21), 0)
        self.assertEqual(validate_rack_quantity(11, 10, 21), 0)

    def test_leave_legacy_stock_unallocated(self):
        self.assertEqual(validate_rack_quantity(10, 0, 21), 11)

    def test_reject_location_allocation_above_physical_balance(self):
        with self.assertRaises(ValidationError):
            validate_rack_quantity(12, 10, 21)

    def test_repeated_same_allocation_has_no_increment(self):
        for _ in range(3):
            self.assertEqual(validate_rack_quantity(21, 0, 21), 0)
