from django.db import models
from apps.common.models import TimeStampedModel


class Shipment(TimeStampedModel):
    TYPE_CHOICES = [("PURCHASE", "Purchase Receipt"), ("SALES", "Sales Delivery")]
    shipment_number = models.CharField(max_length=50, unique=True)
    shipment_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default="PURCHASE"
    )
    purchase_order = models.ForeignKey(
        "purchases.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="shipments",
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="shipments",
    )
    invoice = models.ForeignKey(
        "sales.SalesInvoice", null=True, blank=True, on_delete=models.PROTECT
    )
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.PROTECT
    )
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    shipment_date = models.DateField(null=True, blank=True)
    shipment_method = models.CharField(max_length=80, blank=True)
    courier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    expected_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    received_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_shipments",
    )
    delivery_address = models.TextField(blank=True)
    delivery_person = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="delivery_shipments",
    )
    delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, default="PENDING")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-shipment_date", "-id"]


class ShipmentItem(models.Model):
    CONDITION_CHOICES = [
        ("GOOD", "Good"),
        ("DAMAGED", "Damaged"),
        ("PARTIAL", "Partial"),
    ]
    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant", null=True, blank=True, on_delete=models.PROTECT
    )
    expected_quantity = models.PositiveIntegerField(default=0)
    received_quantity = models.PositiveIntegerField(default=0)
    accepted_quantity = models.PositiveIntegerField(default=0)
    rejected_quantity = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    condition = models.CharField(
        max_length=20, choices=CONDITION_CHOICES, default="GOOD"
    )
    batch_number = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=150, blank=True)
    remarks = models.TextField(blank=True)


class ShipmentTrackingLog(TimeStampedModel):
    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name="tracking_logs"
    )
    status = models.CharField(max_length=30)
    location = models.CharField(max_length=200, blank=True)
    remarks = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
