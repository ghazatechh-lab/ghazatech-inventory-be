from django.db import models
from apps.common.models import TimeStampedModel, BranchAwareModel


class PurchaseOrder(TimeStampedModel, BranchAwareModel):
    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, default="DRAFT")
    payment_status = models.CharField(max_length=30, default="UNPAID")
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_pos",
    )


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)


class GoodsReceivedNote(TimeStampedModel, BranchAwareModel):
    grn_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    received_date = models.DateField()
    received_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=30, default="DRAFT")
    is_confirmed = models.BooleanField(default=False)


class GoodsReceivedItem(models.Model):
    grn = models.ForeignKey(
        GoodsReceivedNote, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    ordered_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField()
    damaged_quantity = models.PositiveIntegerField(default=0)
    accepted_quantity = models.PositiveIntegerField(default=0)
    rack_location = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)


class SupplierBill(TimeStampedModel, BranchAwareModel):
    bill_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    purchase_order = models.ForeignKey(
        PurchaseOrder, null=True, blank=True, on_delete=models.SET_NULL
    )
    bill_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=30, default="UNPAID")
    notes = models.TextField(blank=True)


class SupplierPayment(TimeStampedModel, BranchAwareModel):
    payment_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    supplier_bill = models.ForeignKey(
        SupplierBill, null=True, blank=True, on_delete=models.SET_NULL
    )
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=30)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    paid_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)


class SupplierReturn(TimeStampedModel, BranchAwareModel):
    return_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    grn = models.ForeignKey(GoodsReceivedNote, on_delete=models.PROTECT)
    return_date = models.DateField()
    reason = models.CharField(max_length=150)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, default="DRAFT")
    notes = models.TextField(blank=True)
