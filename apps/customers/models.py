from django.db import models
from apps.common.models import TimeStampedModel, SoftDeleteModel


class Customer(TimeStampedModel, SoftDeleteModel):
    customer_code = models.CharField(max_length=50, unique=True)
    customer_type = models.CharField(max_length=30, default="Retail")
    customer_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    emirate = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="UAE")
    trn_number = models.CharField(max_length=80, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_terms_days = models.PositiveIntegerField(default=0)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.customer_name
