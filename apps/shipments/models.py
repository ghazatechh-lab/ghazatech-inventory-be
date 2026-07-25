from django.db import models

from apps.common.models import (
    TimeStampedModel,
)


class Shipment(TimeStampedModel):
    TYPE_CHOICES = [
        (
            "PURCHASE",
            "Purchase Receipt",
        ),
        (
            "SALES",
            "Sales Delivery",
        ),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING", "Pending"),
        (
            "IN_TRANSIT",
            "In Transit",
        ),
        (
            "CUSTOMS_HOLD",
            "Customs Hold",
        ),
        (
            "DELIVERED",
            "Delivered",
        ),
        (
            "RECEIVED",
            "Received",
        ),
        (
            "COMPLETED",
            "Completed",
        ),
        (
            "CANCELLED",
            "Cancelled",
        ),
    ]

    QC_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PASSED", "Passed"),
        (
            "PASSED_WITH_REJECTIONS",
            "Passed with Rejections",
        ),
        ("FAILED", "Failed"),
    ]

    shipment_number = models.CharField(
        max_length=50,
        unique=True,
    )

    shipment_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="PURCHASE",
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
        "sales.SalesInvoice",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
    )

    warehouse = models.CharField(
        max_length=150,
        blank=True,
    )

    shipment_date = models.DateField(
        null=True,
        blank=True,
    )

    shipment_method = models.CharField(
        max_length=80,
        blank=True,
    )

    courier = models.CharField(
        max_length=120,
        blank=True,
    )

    tracking_number = models.CharField(
        max_length=100,
        blank=True,
    )

    container_number = models.CharField(
        max_length=100,
        blank=True,
    )

    expected_date = models.DateField(
        null=True,
        blank=True,
    )

    received_date = models.DateField(
        null=True,
        blank=True,
    )

    received_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_shipments",
    )

    checked_by_name = models.CharField(
        max_length=150,
        blank=True,
    )

    supplier_invoice_number = models.CharField(
        max_length=100,
        blank=True,
    )

    delivery_note_number = models.CharField(
        max_length=100,
        blank=True,
    )

    delivery_address = models.TextField(
        blank=True,
    )

    delivery_person = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="delivery_shipments",
    )

    delivery_date = models.DateField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )

    qc_status = models.CharField(
        max_length=40,
        choices=QC_STATUS_CHOICES,
        default="PENDING",
    )

    inspection_remarks = models.TextField(
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-shipment_date",
            "-id",
        ]

    def __str__(self):
        return self.shipment_number


class ShipmentItem(models.Model):
    CONDITION_CHOICES = [
        ("NEW", "New"),
        ("USED", "Used"),
        (
            "REFURBISHED",
            "Refurbished",
        ),
        ("DAMAGED", "Damaged"),
    ]

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
    )

    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    expected_quantity = models.PositiveIntegerField(
        default=0,
    )

    received_quantity = models.PositiveIntegerField(
        default=0,
    )

    accepted_quantity = models.PositiveIntegerField(
        default=0,
    )

    rejected_quantity = models.PositiveIntegerField(
        default=0,
    )

    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    vat_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=5,
    )

    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default="NEW",
    )

    rack = models.ForeignKey(
        "inventory.Rack",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shipment_items",
    )

    batch_number = models.CharField(
        max_length=100,
        blank=True,
    )

    serial_number = models.CharField(
        max_length=150,
        blank=True,
    )

    remarks = models.TextField(
        blank=True,
    )

    @property
    def total_amount(self):
        taxable = self.accepted_quantity * self.unit_cost

        return taxable + taxable * self.vat_percentage / 100


class ShipmentTrackingLog(
    TimeStampedModel,
):
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="tracking_logs",
    )

    status = models.CharField(
        max_length=30,
    )

    location = models.CharField(
        max_length=200,
        blank=True,
    )

    remarks = models.TextField(
        blank=True,
    )

    updated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
    )
