from django.conf import settings
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
    order_date = models.DateField(
        null=True,
        blank=True,
    )
    expected_delivery_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="DRAFT")
    payment_status = models.CharField(max_length=30, default="UNPAID")
    supplier_reference = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=5, default="AED")
    other_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    terms_conditions = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
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
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)


def grn_attachment_path(instance, filename):
    return f"grn/{instance.grn_id}/attachments/{filename}"


class GoodsReceivedNote(TimeStampedModel, BranchAwareModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("CONFIRMED", "Confirmed"),
        ("CANCELLED", "Cancelled"),
    ]

    grn_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="grns",
    )
    supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT)
    received_date = models.DateField(
        null=True,
        blank=True,
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="received_grns",
    )
    warehouse_location = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )
    is_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_date", "-id"]


class GoodsReceivedItem(models.Model):
    QUALITY_CHOICES = [
        ("QC_PASSED", "QC Passed"),
        ("PARTIAL_ACCEPT", "Partial Receipt"),
        ("QC_REJECTED", "QC Flagged"),
    ]

    grn = models.ForeignKey(
        GoodsReceivedNote,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    ordered_quantity = models.PositiveIntegerField()
    received_quantity = models.PositiveIntegerField()
    damaged_quantity = models.PositiveIntegerField(default=0)
    accepted_quantity = models.PositiveIntegerField(default=0)
    quality_status = models.CharField(
        max_length=30,
        choices=QUALITY_CHOICES,
        default="QC_PASSED",
    )
    rack = models.ForeignKey(
        "inventory.Rack",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="grn_items",
    )
    remarks = models.TextField(blank=True)


class GRNAttachment(TimeStampedModel):
    grn = models.ForeignKey(
        GoodsReceivedNote,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to=grn_attachment_path)
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_grn_attachments",
    )

    class Meta:
        ordering = ["-created_at"]


def supplier_bill_attachment_path(instance, filename):
    return f"supplier-bills/{instance.bill_id}/attachments/{filename}"


class SupplierBill(TimeStampedModel, BranchAwareModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("UNMATCHED", "Unmatched"),
        ("UNPAID", "Unpaid"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
        ("CANCELLED", "Cancelled"),
    ]

    MATCH_CHOICES = [
        ("UNMATCHED", "Unmatched"),
        ("MATCHED", "Matched"),
    ]

    bill_number = models.CharField(max_length=50, unique=True)
    supplier_invoice_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="supplier_bills",
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_bills",
    )
    grn = models.ForeignKey(
        GoodsReceivedNote,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_bills",
    )
    bill_date = models.DateField(
        null=True,
        blank=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
    )
    payment_terms_days = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=5, default="AED")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )
    match_status = models.CharField(
        max_length=20,
        choices=MATCH_CHOICES,
        default="UNMATCHED",
    )
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_supplier_bills",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-bill_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "supplier_invoice_number"],
                name="unique_supplier_invoice_number",
            )
        ]


class SupplierBillItem(models.Model):
    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.CASCADE,
        related_name="items",
    )
    grn_item = models.ForeignKey(
        GoodsReceivedItem,
        on_delete=models.PROTECT,
        related_name="bill_items",
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    received_quantity = models.PositiveIntegerField()
    bill_quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)


class SupplierBillAttachment(TimeStampedModel):
    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to=supplier_bill_attachment_path)
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_supplier_bill_attachments",
    )

    class Meta:
        ordering = ["-created_at"]


def supplier_payment_attachment_path(instance, filename):
    return f"supplier-payments/{instance.payment_id}/attachments/{filename}"


class SupplierPayment(TimeStampedModel, BranchAwareModel):
    METHOD_CHOICES = [
        ("BANK_TRANSFER", "Bank Transfer"),
        ("CHEQUE", "Cheque"),
        ("CASH", "Cash"),
        ("CARD", "Card"),
        ("OTHER", "Other"),
    ]

    payment_number = models.CharField(
        max_length=50,
        unique=True,
    )

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="supplier_payments",
    )

    payment_date = models.DateField(
        null=True,
        blank=True,
    )

    payment_method = models.CharField(
        max_length=30,
        choices=METHOD_CHOICES,
        null=True,
        blank=True,
    )

    bank_account = models.ForeignKey(
        "finance.BankAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_payments",
    )

    cash_register = models.ForeignKey(
        "finance.CashRegister",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_payments",
    )

    reference_number = models.CharField(
        max_length=120,
        blank=True,
    )

    cheque_number = models.CharField(
        max_length=100,
        blank=True,
    )

    cheque_date = models.DateField(
        null=True,
        blank=True,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    notes = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-payment_date",
            "-id",
        ]


class SupplierPaymentAllocation(models.Model):
    payment = models.ForeignKey(
        SupplierPayment,
        on_delete=models.CASCADE,
        related_name="allocations",
    )

    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.PROTECT,
        related_name="payment_allocations",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "payment",
                    "bill",
                ],
                name="unique_payment_bill_allocation",
            )
        ]


class SupplierPaymentAttachment(TimeStampedModel):
    payment = models.ForeignKey(
        SupplierPayment,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    file = models.FileField(
        upload_to=supplier_payment_attachment_path,
    )

    original_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    file_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        default=0,
    )

    content_type = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_supplier_payment_attachments",
    )

    class Meta:
        ordering = [
            "-created_at",
        ]


def supplier_return_attachment_path(instance, filename):
    return f"supplier-returns/{instance.supplier_return_id}/attachments/{filename}"


class SupplierReturn(TimeStampedModel, BranchAwareModel):
    REASON_CHOICES = [
        ("DAMAGED_IN_TRANSIT", "Damaged in transit"),
        ("QUALITY_ISSUE", "Quality issue"),
        ("WRONG_ITEM", "Wrong item shipped"),
        ("EXCESS_QUANTITY", "Excess quantity"),
        ("OTHER", "Other"),
    ]

    RESOLUTION_CHOICES = [
        ("SUPPLIER_CREDIT_NOTE", "Supplier credit note"),
        ("ADJUST_NEXT_BILL", "Adjust next bill"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("CREDIT_ISSUED", "Credit Issued"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]

    return_number = models.CharField(
        max_length=50,
        unique=True,
    )

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="supplier_returns",
    )

    grn = models.ForeignKey(
        GoodsReceivedNote,
        on_delete=models.PROTECT,
        related_name="supplier_returns",
    )

    return_date = models.DateField(
        null=True,
        blank=True,
    )

    reason = models.CharField(
        max_length=50,
        choices=REASON_CHOICES,
        default="OTHER",
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )

    notes = models.TextField(
        blank=True,
    )

    details = models.TextField(
        null=True,
        blank=True,
    )

    resolution = models.CharField(
        max_length=40,
        choices=RESOLUTION_CHOICES,
        null=True,
        blank=True,
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_supplier_returns",
    )

    vendor_credit = models.ForeignKey(
        "purchases.VendorCredit",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_supplier_returns",
    )

    class Meta:
        ordering = [
            "-return_date",
            "-id",
        ]


class SupplierReturnItem(models.Model):
    supplier_return = models.ForeignKey(
        SupplierReturn,
        on_delete=models.CASCADE,
        related_name="items",
    )

    grn_item = models.ForeignKey(
        GoodsReceivedItem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_return_items",
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

    received_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    quantity = models.PositiveIntegerField()

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    reason = models.CharField(
        max_length=200,
        blank=True,
    )


class SupplierReturnAttachment(TimeStampedModel):
    supplier_return = models.ForeignKey(
        SupplierReturn,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    file = models.FileField(
        upload_to=supplier_return_attachment_path,
    )

    original_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    file_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )

    content_type = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_supplier_return_attachments",
    )

    class Meta:
        ordering = [
            "-created_at",
        ]


def vendor_credit_attachment_path(instance, filename):
    return f"vendor-credits/{instance.vendor_credit_id}/attachments/{filename}"


class VendorCredit(TimeStampedModel, BranchAwareModel):
    REASON_CHOICES = [
        ("RETURN", "Return"),
        ("DAMAGED_GOODS", "Damaged goods"),
        ("OVERBILLING", "Overbilling"),
        ("PRICE_ADJUSTMENT", "Price adjustment"),
        ("FREIGHT_ADJUSTMENT", "Freight adjustment"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("OPEN", "Open"),
        ("PARTIALLY_APPLIED", "Partially Applied"),
        ("FULLY_APPLIED", "Fully Applied"),
        ("VOID", "Void"),
    ]

    credit_number = models.CharField(
        max_length=50,
        unique=True,
    )

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vendor_credits",
    )

    supplier_return = models.ForeignKey(
        SupplierReturn,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_credits",
    )

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_credits",
    )

    supplier_bill = models.ForeignKey(
        SupplierBill,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_credits",
    )

    credit_date = models.DateField(
        null=True,
        blank=True,
    )

    currency = models.CharField(
        max_length=5,
        null=True,
        blank=True,
        default="AED",
    )

    reference_number = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    reason = models.CharField(
        max_length=40,
        choices=REASON_CHOICES,
        null=True,
        blank=True,
        default="OTHER",
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    applied_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    remaining_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )

    notes = models.TextField(
        null=True,
        blank=True,
    )

    internal_memo = models.TextField(
        null=True,
        blank=True,
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_vendor_credits",
    )

    approval_date = models.DateField(
        null=True,
        blank=True,
    )

    posted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    voided_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    void_reason = models.TextField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-credit_date",
            "-id",
        ]


class VendorCreditItem(models.Model):
    vendor_credit = models.ForeignKey(
        VendorCredit,
        on_delete=models.CASCADE,
        related_name="items",
    )

    description = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    gl_account = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=1,
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    tax_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )


class VendorCreditApplication(TimeStampedModel):
    vendor_credit = models.ForeignKey(
        VendorCredit,
        on_delete=models.CASCADE,
        related_name="applications",
    )

    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.PROTECT,
        related_name="vendor_credit_applications",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "vendor_credit",
                    "bill",
                ],
                name="unique_vendor_credit_bill_application",
            )
        ]


class VendorCreditAttachment(TimeStampedModel):
    vendor_credit = models.ForeignKey(
        VendorCredit,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    file = models.FileField(
        upload_to=vendor_credit_attachment_path,
    )

    original_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    file_size = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )

    content_type = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_vendor_credit_attachments",
    )

    class Meta:
        ordering = [
            "-created_at",
        ]


def purchase_expense_attachment_path(instance, filename):
    return f"purchase-expenses/{instance.expense_id}/attachments/{filename}"


class PurchaseExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseExpense(TimeStampedModel, BranchAwareModel):
    CATEGORY_CHOICES = [
        ("RENT_UTILITIES", "Rent & Utilities"),
        ("OFFICE", "Office"),
        ("TRANSPORT", "Transport"),
        ("MAINTENANCE", "Maintenance"),
        ("MARKETING", "Marketing"),
        ("PROFESSIONAL_FEES", "Professional Fees"),
        ("TRAVEL", "Travel"),
        ("MISCELLANEOUS", "Miscellaneous"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("BANK_TRANSFER", "Bank Transfer"),
        ("CHEQUE", "Cheque"),
        ("CASH", "Cash"),
        ("CARD", "Company Card"),
        ("PETTY_CASH", "Petty Cash"),
        ("OTHER", "Other"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("PAID", "Paid"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]

    expense_number = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(
        max_length=40, choices=CATEGORY_CHOICES, null=True, blank=True
    )
    expense_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, default=0
    )
    vendor_name = models.CharField(max_length=150, null=True, blank=True)
    payment_method = models.CharField(
        max_length=30, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True
    )
    bank_account = models.ForeignKey(
        "finance.BankAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_expenses",
    )
    cash_register = models.ForeignKey(
        "finance.CashRegister",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_expenses",
    )
    reference_number = models.CharField(max_length=120, null=True, blank=True)
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, null=True, blank=True, default="PENDING"
    )
    notes = models.TextField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_purchase_expenses",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_purchase_expenses",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-expense_date", "-id"]


class PurchaseExpenseAttachment(TimeStampedModel):
    expense = models.ForeignKey(
        PurchaseExpense, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=purchase_expense_attachment_path)
    original_name = models.CharField(max_length=255, null=True, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=120, null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_purchase_expense_attachments",
    )

    class Meta:
        ordering = ["-created_at"]
