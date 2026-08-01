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
    tax_scope = models.CharField(max_length=30, default="OUT_OF_SCOPE")
    transfer_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    capitalized_vat_value = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    courier_cost_excluding_vat = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    courier_vat_treatment = models.CharField(max_length=30, default="OUT_OF_SCOPE")
    courier_vat_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )
    courier_vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    courier_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_transfer_cost = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    source_stock_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    destination_stock_value = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    reconciliation_status = models.CharField(max_length=30, default="PENDING")
    value_difference = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    approved_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)


class StockTransferItem(models.Model):
    transfer = models.ForeignKey(
        StockTransfer, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transfer_items",
    )
    requested_quantity = models.PositiveIntegerField()
    dispatched_quantity = models.PositiveIntegerField(default=0)
    received_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    remarks = models.TextField(blank=True)
    stock_classification = models.CharField(max_length=20, default="REGULAR")
    transfer_unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    line_transfer_value = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    source_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    destination_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    value_difference = models.DecimalField(max_digits=16, decimal_places=2, default=0)
