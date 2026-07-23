from django.db import models
from apps.common.models import TimeStampedModel, BranchAwareModel


class PurchaseOrder(TimeStampedModel, BranchAwareModel):
    STATUS_CHOICES = [
        (x, x.title().replace("_", " "))
        for x in [
            "DRAFT",
            "PENDING_APPROVAL",
            "APPROVED",
            "PARTIALLY_RECEIVED",
            "RECEIVED",
            "CANCELLED",
        ]
    ]
    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="DRAFT")
    payment_status = models.CharField(max_length=30, default="UNPAID")
    supplier_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_pos",
    )

    class Meta:
        ordering = ["-order_date", "-id"]


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant", null=True, blank=True, on_delete=models.PROTECT
    )
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
    warehouse_location = models.CharField(max_length=150, blank=True)
    attachment = models.FileField(upload_to="grn/", null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=30, default="DRAFT")
    is_confirmed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-received_date", "-id"]


class GoodsReceivedItem(models.Model):
    QUALITY_CHOICES = [
        ("QC_PASSED", "QC Passed"),
        ("PARTIAL_ACCEPT", "Partial Accept"),
        ("QC_REJECTED", "QC Rejected"),
    ]
    grn = models.ForeignKey(
        GoodsReceivedNote, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant", null=True, blank=True, on_delete=models.PROTECT
    )
    ordered_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField()
    damaged_quantity = models.PositiveIntegerField(default=0)
    accepted_quantity = models.PositiveIntegerField(default=0)
    quality_status = models.CharField(
        max_length=30, choices=QUALITY_CHOICES, default="QC_PASSED"
    )
    rack_location = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)


class SupplierBill(TimeStampedModel, BranchAwareModel):
    bill_number = models.CharField(max_length=50, unique=True)
    supplier_invoice_number = models.CharField(max_length=100, blank=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    purchase_order = models.ForeignKey(
        PurchaseOrder, null=True, blank=True, on_delete=models.SET_NULL
    )
    grn = models.ForeignKey(
        GoodsReceivedNote, null=True, blank=True, on_delete=models.SET_NULL
    )
    bill_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=30, default="UNPAID")
    attachment = models.FileField(upload_to="supplier_bills/", null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-bill_date", "-id"]


class SupplierPayment(TimeStampedModel, BranchAwareModel):
    payment_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=30)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_number = models.CharField(max_length=100, blank=True)
    paid_from = models.CharField(max_length=150, blank=True)
    attachment = models.FileField(upload_to="supplier_payments/", null=True, blank=True)
    notes = models.TextField(blank=True)
    paid_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-payment_date", "-id"]


class SupplierPaymentAllocation(models.Model):
    payment = models.ForeignKey(
        SupplierPayment, on_delete=models.CASCADE, related_name="allocations"
    )
    bill = models.ForeignKey(
        SupplierBill, on_delete=models.PROTECT, related_name="payment_allocations"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        unique_together = [("payment", "bill")]


class SupplierReturn(TimeStampedModel, BranchAwareModel):
    return_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    grn = models.ForeignKey(GoodsReceivedNote, on_delete=models.PROTECT)
    return_date = models.DateField()
    reason = models.CharField(max_length=150)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, default="DRAFT")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-return_date", "-id"]


class SupplierReturnItem(models.Model):
    supplier_return = models.ForeignKey(
        SupplierReturn, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant", null=True, blank=True, on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reason = models.CharField(max_length=200, blank=True)


class VendorCredit(TimeStampedModel, BranchAwareModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("OPEN", "Open"),
        ("PARTIALLY_APPLIED", "Partially Applied"),
        ("APPLIED", "Applied"),
        ("VOID", "Void"),
    ]
    credit_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    supplier_return = models.ForeignKey(
        SupplierReturn, null=True, blank=True, on_delete=models.SET_NULL
    )
    credit_date = models.DateField()
    reason = models.CharField(max_length=200)
    reference_number = models.CharField(max_length=100, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    applied_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="DRAFT")
    attachment = models.FileField(upload_to="vendor_credits/", null=True, blank=True)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_vendor_credits",
    )
    approval_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-credit_date", "-id"]


class VendorCreditApplication(models.Model):
    vendor_credit = models.ForeignKey(
        VendorCredit, on_delete=models.CASCADE, related_name="applications"
    )
    bill = models.ForeignKey(
        SupplierBill, on_delete=models.PROTECT, related_name="credit_applications"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    applied_at = models.DateTimeField(auto_now_add=True)


class PurchaseExpense(TimeStampedModel, BranchAwareModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("PAID", "Paid"),
        ("REJECTED", "Rejected"),
    ]
    expense_number = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=250)
    category = models.CharField(max_length=100)
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    vendor_name = models.CharField(max_length=200, blank=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True, on_delete=models.SET_NULL
    )
    payment_method = models.CharField(max_length=50)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="PENDING")
    receipt = models.FileField(upload_to="purchase_expenses/", null=True, blank=True)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_purchase_expenses",
    )

    class Meta:
        ordering = ["-expense_date", "-id"]
