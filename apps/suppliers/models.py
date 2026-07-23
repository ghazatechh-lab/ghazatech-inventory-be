from django.db import models
from apps.common.models import TimeStampedModel, SoftDeleteModel


class Supplier(TimeStampedModel, SoftDeleteModel):
    CATEGORY_CHOICES = [
        ("LAPTOPS", "Laptops"),
        ("ELECTRONICS", "Electronics & Components"),
        ("SPARE_PARTS", "Spare Parts"),
        ("SERVICES", "Services"),
        ("OTHER", "Other"),
    ]
    CURRENCY_CHOICES = [("AED", "AED"), ("USD", "USD"), ("EUR", "EUR"), ("INR", "INR")]

    supplier_code = models.CharField(max_length=50, unique=True)
    supplier_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    supplier_type = models.CharField(max_length=50, default="Local Supplier")
    supplier_category = models.CharField(
        max_length=40, choices=CATEGORY_CHOICES, default="ELECTRONICS"
    )
    contact_person = models.CharField(max_length=150, blank=True)
    designation = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    billing_address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="UAE")
    trn_number = models.CharField(max_length=80, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_terms_days = models.PositiveIntegerField(default=15)
    currency = models.CharField(max_length=5, choices=CURRENCY_CHOICES, default="AED")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_name = models.CharField(max_length=150, blank=True)
    account_holder_name = models.CharField(max_length=150, blank=True)
    iban = models.CharField(max_length=100, blank=True)
    swift_code = models.CharField(max_length=50, blank=True)
    auto_block_credit_limit = models.BooleanField(default=True)
    send_payment_reminders = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["supplier_name"]
        indexes = [
            models.Index(fields=["supplier_name"]),
            models.Index(fields=["supplier_code"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.supplier_name
