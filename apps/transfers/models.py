from django.db import models
from apps.common.models import TimeStampedModel


class StockTransfer(TimeStampedModel):
    transfer_number = models.CharField(max_length=50, unique=True)
    from_branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="outgoing_transfers"
    )
    to_branch = models.ForeignKey(
        "branches.Branch", on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="requested_transfers",
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_transfers",
    )
    dispatched_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispatched_transfers",
    )
    received_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_transfers",
    )
    transfer_date = models.DateField()
    dispatch_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, default="DRAFT")
    notes = models.TextField(blank=True)


class StockTransferItem(models.Model):
    transfer = models.ForeignKey(
        StockTransfer, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    requested_quantity = models.PositiveIntegerField()
    dispatched_quantity = models.PositiveIntegerField(default=0)
    received_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    remarks = models.TextField(blank=True)
