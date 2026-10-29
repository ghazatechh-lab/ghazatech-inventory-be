from django.db import models
from apps.common.models import TimeStampedModel


class Branch(TimeStampedModel):
    TAX_VAT = "VAT"
    TAX_NON_VAT = "NON_VAT"
    TAX_MODE_CHOICES = ((TAX_VAT, "VAT"), (TAX_NON_VAT, "Non-VAT"))
    # Tax classification is independent of the branch's functional type.
    # Existing branches are backfilled by migration, BR03 remains virtual.
    tax_mode = models.CharField(max_length=10, choices=TAX_MODE_CHOICES, blank=True, default="")
    branch_code = models.CharField(max_length=30, unique=True)
    branch_name = models.CharField(max_length=150)
    branch_type = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    emirate = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="UAE")
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    manager = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_branches",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["branch_code", "is_active"])]

    def __str__(self):
        return self.branch_name
