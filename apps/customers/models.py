from django.db import models

from apps.common.models import SoftDeleteModel, TimeStampedModel


class Customer(TimeStampedModel, SoftDeleteModel):
    CUSTOMER_TYPE_CHOICES = [
        ("BUSINESS", "Business"),
        ("INDIVIDUAL", "Individual"),
    ]

    CATEGORY_CHOICES = [
        ("RETAIL", "Retail"),
        ("WHOLESALE", "Wholesale"),
        ("CORPORATE", "Corporate"),
        ("LEAD", "Lead"),
    ]

    PAYMENT_TERMS_CHOICES = [
        ("DUE_ON_RECEIPT", "Due on Receipt"),
        ("NET_15", "Net 15"),
        ("NET_30", "Net 30"),
        ("NET_60", "Net 60"),
    ]

    customer_code = models.CharField(
        max_length=50,
        unique=True,
    )

    customer_type = models.CharField(
        max_length=30,
        choices=CUSTOMER_TYPE_CHOICES,
        null=True,
        blank=True,
        default="BUSINESS",
    )

    customer_name = models.CharField(
        max_length=200,
    )

    contact_person = models.CharField(
        max_length=150,
        null=True,
        blank=True,
    )

    phone = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    whatsapp_number = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    email = models.EmailField(
        null=True,
        blank=True,
    )

    address = models.TextField(
        null=True,
        blank=True,
    )

    billing_address = models.TextField(
        null=True,
        blank=True,
    )

    city = models.CharField(
        max_length=80,
        null=True,
        blank=True,
    )

    emirate = models.CharField(
        max_length=80,
        null=True,
        blank=True,
    )

    country = models.CharField(
        max_length=80,
        null=True,
        blank=True,
        default="UAE",
    )

    trn_number = models.CharField(
        max_length=80,
        null=True,
        blank=True,
    )

    trn = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    trade_license = models.CharField(
        max_length=60,
        null=True,
        blank=True,
    )

    credit_limit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    payment_terms_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=30,
    )

    payment_terms = models.CharField(
        max_length=30,
        choices=PAYMENT_TERMS_CHOICES,
        null=True,
        blank=True,
        default="NET_30",
    )

    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        null=True,
        blank=True,
        default="RETAIL",
    )

    opening_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    notes = models.TextField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["customer_name", "id"]

    def __str__(self):
        return self.customer_name
