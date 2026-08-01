from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.inventory.models import ProductStock


class ClassifiedStockPropertiesTests(TestCase):
    def test_total_and_available_balances(self):
        stock = ProductStock(
            regular_quantity=20,
            restricted_quantity=5,
            reserved_regular_quantity=2,
            reserved_restricted_quantity=1,
        )
        self.assertEqual(stock.total_quantity, 25)
        self.assertEqual(stock.available_regular_quantity, 18)
        self.assertEqual(stock.available_restricted_quantity, 4)
        self.assertEqual(stock.total_available_quantity, 22)
