from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class BranchAware(models.Model):
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    TAX_TREATMENTS = [
        ("STANDARD_VAT", "Standard VAT"),
        ("ZERO_RATED", "Zero Rated"),
        ("EXEMPT", "Exempt"),
        ("NON_TAXABLE", "Non Taxable"),
    ]
    tax_treatment = models.CharField(
        max_length=30, choices=TAX_TREATMENTS, default="STANDARD_VAT"
    )
    tax_inclusive = models.BooleanField(default=False)
    tax_reason = models.CharField(max_length=255, blank=True, default="")
    supporting_reference = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        abstract = True


class DocumentBase(TimeStampedModel, BranchAware):
    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    currency = models.CharField(
        max_length=5,
        null=True,
        blank=True,
        default="AED",
    )

    subtotal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    discount_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    vat_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    shipping_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    total_amount = models.DecimalField(
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

    class Meta:
        abstract = True


class Quotation(DocumentBase):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("PENDING", "Pending"),
        ("ACCEPTED", "Accepted"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
        ("CONVERTED", "Converted"),
    ]

    quote_number = models.CharField(
        max_length=50,
        unique=True,
    )

    quote_date = models.DateField(
        null=True,
        blank=True,
    )

    valid_until = models.DateField(
        null=True,
        blank=True,
    )

    payment_terms = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    delivery_terms = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )

    sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    rejected_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    converted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-quote_date",
            "-id",
        ]

    def __str__(self):
        return self.quote_number


class SalesOrder(DocumentBase):
    DELIVERY_METHOD_CHOICES = [
        ("OWN_FLEET", "Own Fleet Delivery"),
        ("COURIER", "Courier"),
        ("CUSTOMER_PICKUP", "Customer Pickup"),
        ("THIRD_PARTY", "Third-Party Transport"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING", "Pending"),
        ("CONFIRMED", "Confirmed"),
        ("AWAITING_FULFILLMENT", "Awaiting Fulfillment"),
        ("PARTIALLY_FULFILLED", "Partially Fulfilled"),
        ("FULFILLED", "Fulfilled"),
        ("CANCELLED", "Cancelled"),
    ]

    order_number = models.CharField(
        max_length=50,
        unique=True,
    )

    quotation = models.ForeignKey(
        Quotation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_orders",
    )

    order_date = models.DateField(
        null=True,
        blank=True,
    )

    delivery_date = models.DateField(
        null=True,
        blank=True,
    )

    delivery_method = models.CharField(
        max_length=30,
        choices=DELIVERY_METHOD_CHOICES,
        null=True,
        blank=True,
        default="OWN_FLEET",
    )

    shipping_address = models.TextField(
        null=True,
        blank=True,
    )

    emirate = models.CharField(
        max_length=60,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    fulfilled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-order_date",
            "-id",
        ]

    def __str__(self):
        return self.order_number


class SalesInvoice(DocumentBase):
    PAYMENT_TERMS_CHOICES = [
        ("DUE_ON_RECEIPT", "Due on Receipt"),
        ("NET_7", "Net 7"),
        ("NET_15", "Net 15"),
        ("NET_30", "Net 30"),
        ("NET_45", "Net 45"),
        ("NET_60", "Net 60"),
    ]

    SALE_TYPE_CHOICES = [
        ("ORDER", "Sales Order"),
        ("STANDALONE", "Standalone"),
        ("POS", "POS"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("UNPAID", "Unpaid"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
        ("OVERDUE", "Overdue"),
        ("VOID", "Void"),
    ]

    DELIVERY_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PARTIALLY_DELIVERED", "Partially Delivered"),
        ("DELIVERED", "Delivered"),
        ("CANCELLED", "Cancelled"),
    ]

    invoice_number = models.CharField(
        max_length=50,
        unique=True,
    )

    sales_order = models.ForeignKey(
        SalesOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )

    invoice_date = models.DateField(
        null=True,
        blank=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
    )

    customer_po_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    payment_terms = models.CharField(
        max_length=30,
        choices=PAYMENT_TERMS_CHOICES,
        null=True,
        blank=True,
        default="NET_30",
    )

    sale_type = models.CharField(
        max_length=20,
        choices=SALE_TYPE_CHOICES,
        null=True,
        blank=True,
        default="STANDALONE",
    )

    paid_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    balance_due = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    payment_status = models.CharField(
        max_length=30,
        choices=PAYMENT_STATUS_CHOICES,
        null=True,
        blank=True,
        default="UNPAID",
    )

    delivery_status = models.CharField(
        max_length=30,
        choices=DELIVERY_STATUS_CHOICES,
        null=True,
        blank=True,
        default="PENDING",
    )

    bank_account = models.ForeignKey(
        "finance.BankAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    send_payment_reminders = models.BooleanField(
        default=False,
    )

    issued_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    voided_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-invoice_date",
            "-id",
        ]

    def __str__(self):
        return self.invoice_number


class SalesLineBase(models.Model):
    product = models.ForeignKey(
        "inventory.Product",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    description = models.CharField(
        max_length=255,
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

    vat_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=5,
    )

    TAX_TREATMENTS = [
        ("STANDARD_VAT", "Standard VAT"),
        ("ZERO_RATED", "Zero Rated"),
        ("EXEMPT", "Exempt"),
        ("NON_TAXABLE", "Non Taxable"),
    ]
    STOCK_CLASSIFICATIONS = [
        ("REGULAR", "Regular"),
        ("RESTRICTED", "Restricted"),
    ]
    stock_classification = models.CharField(
        max_length=20, choices=STOCK_CLASSIFICATIONS, default="REGULAR"
    )
    tax_treatment = models.CharField(
        max_length=30, choices=TAX_TREATMENTS, default="STANDARD_VAT"
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_reason = models.CharField(max_length=255, blank=True, default="")

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        abstract = True


class QuotationItem(SalesLineBase):
    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name="items",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quotation.quote_number} - {self.product or self.description}"


class SalesOrderItem(SalesLineBase):
    sales_order = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )

    fulfilled_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.sales_order.order_number} - {self.product or self.description}"


class SalesInvoiceItem(SalesLineBase):
    invoice = models.ForeignKey(
        SalesInvoice,
        on_delete=models.CASCADE,
        related_name="items",
    )

    sales_order_item = models.ForeignKey(
        SalesOrderItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_items",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.product or self.description}"


class POSSale(DocumentBase):
    PAYMENT_METHOD_CHOICES = [
        ("CASH", "Cash"),
        ("CARD", "Card"),
        ("SPLIT", "Split"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PAID", "Paid"),
        ("VOID", "Void"),
    ]

    receipt_number = models.CharField(
        max_length=50,
        unique=True,
    )

    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_sales",
    )

    sale_datetime = models.DateTimeField(
        null=True,
        blank=True,
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        null=True,
        blank=True,
        default="CASH",
    )

    cash_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    card_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="PAID",
    )

    completed_at = models.DateTimeField(
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
            "-sale_datetime",
            "-id",
        ]

    def __str__(self):
        return self.receipt_number


class POSSaleItem(SalesLineBase):
    sale = models.ForeignKey(
        POSSale,
        on_delete=models.CASCADE,
        related_name="items",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.sale.receipt_number} - {self.product or self.description}"


class SalesCreditNote(DocumentBase):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("ISSUED", "Issued"),
        ("PARTIALLY_REFUNDED", "Partially Refunded"),
        ("REFUNDED", "Refunded"),
        ("VOID", "Void"),
    ]

    REASON_CHOICES = [
        ("RETURN_DAMAGED", "Return / Damaged Goods"),
        ("PRICING_ERROR", "Pricing Error"),
        ("DISCOUNT_ADJUSTMENT", "Discount Adjustment"),
        ("ORDER_CANCELLED", "Order Cancelled"),
        ("OTHER", "Other"),
    ]

    REFUND_METHOD_CHOICES = [
        ("CUSTOMER_CREDIT", "Credit to Customer Account"),
        ("BANK_REFUND", "Bank Refund"),
        ("CASH_REFUND", "Cash Refund"),
    ]

    credit_note_number = models.CharField(
        max_length=50,
        unique=True,
    )

    invoice = models.ForeignKey(
        SalesInvoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_notes",
    )

    credit_date = models.DateField(
        null=True,
        blank=True,
    )

    reason = models.CharField(
        max_length=40,
        choices=REASON_CHOICES,
        null=True,
        blank=True,
    )

    refund_method = models.CharField(
        max_length=30,
        choices=REFUND_METHOD_CHOICES,
        null=True,
        blank=True,
        default="CUSTOMER_CREDIT",
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )

    issued_at = models.DateTimeField(
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

    def __str__(self):
        return self.credit_note_number


class SalesCreditNoteItem(SalesLineBase):
    credit_note = models.ForeignKey(
        SalesCreditNote,
        on_delete=models.CASCADE,
        related_name="items",
    )

    invoice_item = models.ForeignKey(
        SalesInvoiceItem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_note_items",
    )

    invoiced_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    credit_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.credit_note.credit_note_number} - {self.product or self.description}"


class SalesPayment(TimeStampedModel, BranchAware):
    PAYMENT_METHOD_CHOICES = [
        ("CASH", "Cash"),
        ("BANK_TRANSFER", "Bank Transfer"),
        ("CARD", "Card"),
        ("CHEQUE", "Cheque"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING", "Pending Clearance"),
        ("PAID", "Paid / Cleared"),
        ("FAILED", "Failed"),
        ("REVERSED", "Reversed"),
    ]

    payment_number = models.CharField(
        max_length=50,
        unique=True,
    )

    invoice = models.ForeignKey(
        SalesInvoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    payment_date = models.DateField(
        null=True,
        blank=True,
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    currency = models.CharField(
        max_length=5,
        null=True,
        blank=True,
        default="AED",
    )

    payment_method = models.CharField(
        max_length=30,
        choices=PAYMENT_METHOD_CHOICES,
        null=True,
        blank=True,
    )

    bank_account = models.ForeignKey(
        "finance.BankAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    cash_register = models.ForeignKey(
        "finance.CashRegister",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    reference_number = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="PAID",
    )

    notes = models.TextField(
        null=True,
        blank=True,
    )

    cleared_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reversed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reversed_reason = models.TextField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-payment_date",
            "-id",
        ]

    def __str__(self):
        return self.payment_number


class DeliveryNote(TimeStampedModel, BranchAware):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("IN_TRANSIT", "In Transit"),
        ("DELIVERED", "Delivered"),
        ("PARTIALLY_DELIVERED", "Partially Delivered"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
        # Legacy statuses retained for existing records.
        ("DRAFT", "Draft"),
        ("READY", "Ready for Delivery"),
        ("DISPATCHED", "Dispatched"),
    ]

    delivery_note_number = models.CharField(max_length=50, unique=True)
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="delivery_notes"
    )
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.PROTECT
    )
    delivery_date = models.DateField(null=True, blank=True)
    courier = models.CharField(max_length=150, null=True, blank=True)
    tracking_number = models.CharField(max_length=120, null=True, blank=True)
    invoice = models.ForeignKey(
        "SalesInvoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="delivery_notes",
    )
    driver_name = models.CharField(max_length=150, null=True, blank=True)
    vehicle = models.CharField(max_length=150, null=True, blank=True)
    dispatch_datetime = models.DateTimeField(null=True, blank=True)
    expected_delivery_datetime = models.DateTimeField(null=True, blank=True)
    received_by = models.CharField(max_length=150, null=True, blank=True)
    actual_delivery_datetime = models.DateTimeField(null=True, blank=True)
    signature_stamp = models.TextField(null=True, blank=True)
    delivery_address = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    notes = models.TextField(null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-delivery_date", "-id"]

    def __str__(self):
        return self.delivery_note_number


class DeliveryNoteItem(models.Model):
    delivery_note = models.ForeignKey(
        DeliveryNote, on_delete=models.CASCADE, related_name="items"
    )
    sales_order_item = models.ForeignKey(
        SalesOrderItem, null=True, blank=True, on_delete=models.PROTECT
    )
    product = models.ForeignKey(
        "inventory.Product", null=True, blank=True, on_delete=models.PROTECT
    )
    variant = models.ForeignKey(
        "inventory.ProductVariant", null=True, blank=True, on_delete=models.PROTECT
    )
    description = models.CharField(max_length=255, null=True, blank=True)
    ordered_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivered_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    serial_imei = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.delivery_note.delivery_note_number} - {self.product or self.description}"


class SalesReturn(DocumentBase):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("COMPLETED", "Completed"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]

    REASON_CHOICES = [
        ("DAMAGED", "Damaged / Defective"),
        ("DEFECTIVE", "Defective"),
        ("WRONG_ITEM", "Wrong Item Shipped"),
        ("CUSTOMER_REQUEST", "Customer Changed Mind"),
        ("QUALITY_ISSUE", "Quality Issue"),
        ("OTHER", "Other"),
    ]

    RESOLUTION_CHOICES = [
        ("REFUND", "Refund"),
        ("CREDIT_NOTE", "Credit Note"),
        ("REPLACEMENT", "Replacement"),
        ("STORE_CREDIT", "Store Credit"),
    ]

    return_number = models.CharField(
        max_length=50,
        unique=True,
    )

    sales_order = models.ForeignKey(
        SalesOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="returns",
    )

    invoice = models.ForeignKey(
        SalesInvoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="returns",
    )

    return_date = models.DateField(
        null=True,
        blank=True,
    )

    reason = models.CharField(
        max_length=40,
        choices=REASON_CHOICES,
        null=True,
        blank=True,
    )

    resolution = models.CharField(
        max_length=30,
        choices=RESOLUTION_CHOICES,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_sales_returns",
    )

    DISPOSITION_CHOICES = [
        ("RESTOCK", "Restock"),
        ("SCRAP", "Scrap"),
        ("RETURN_TO_SUPPLIER", "Return to Supplier"),
    ]
    disposition = models.CharField(
        max_length=30, choices=DISPOSITION_CHOICES, default="RESTOCK"
    )
    restock_branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restocked_sales_returns",
    )
    refund_method = models.CharField(max_length=60, null=True, blank=True)
    approver_name = models.CharField(max_length=150, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        ordering = [
            "-return_date",
            "-id",
        ]

    def __str__(self):
        return self.return_number


class SalesReturnItem(models.Model):
    CONDITION_CHOICES = [
        ("SELLABLE", "Sellable"),
        ("DAMAGED", "Damaged"),
        ("DEFECTIVE", "Defective"),
        ("SCRAP", "Scrap"),
    ]

    sales_return = models.ForeignKey(
        SalesReturn,
        on_delete=models.CASCADE,
        related_name="items",
    )

    sales_order_item = models.ForeignKey(
        SalesOrderItem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="return_items",
    )

    product = models.ForeignKey(
        "inventory.Product",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    ordered_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    returned_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    condition = models.CharField(
        max_length=30,
        choices=CONDITION_CHOICES,
        null=True,
        blank=True,
        default="SELLABLE",
    )

    serial_imei = models.CharField(max_length=255, null=True, blank=True)
    inspected_by_name = models.CharField(max_length=150, null=True, blank=True)

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.sales_return.return_number} - {self.product}"


class PriceList(TimeStampedModel, BranchAware):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SCHEDULED", "Scheduled"),
        ("ACTIVE", "Active"),
        ("INACTIVE", "Inactive"),
        ("EXPIRED", "Expired"),
    ]

    TYPE_CHOICES = [
        ("CUSTOMER_TIER", "Customer-Tier"),
        ("BRANCH_SPECIFIC", "Branch-Specific"),
        ("PROMOTIONAL", "Promotional"),
    ]

    APPLIES_TO_CHOICES = [
        ("ALL_CUSTOMERS", "All Customers"),
        ("CUSTOMER_CATEGORY", "Customer Category"),
        ("SELECTED_ACCOUNTS", "Selected Accounts"),
    ]

    DISCOUNT_TYPE_CHOICES = [
        ("PERCENTAGE", "Percentage Off"),
        ("FIXED", "Fixed Amount Off"),
        ("CUSTOM_PRICE", "Custom Item Prices"),
    ]

    name = models.CharField(
        max_length=120,
    )

    currency = models.CharField(max_length=3, default="AED")

    price_list_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES,
        default="CUSTOMER_TIER",
    )

    auto_apply = models.BooleanField(default=True)
    stackable = models.BooleanField(default=False)
    usage_limit_per_customer = models.PositiveIntegerField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )

    applies_to = models.CharField(
        max_length=30,
        choices=APPLIES_TO_CHOICES,
        null=True,
        blank=True,
        default="ALL_CUSTOMERS",
    )

    customer_category = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_TYPE_CHOICES,
        null=True,
        blank=True,
        default="PERCENTAGE",
    )

    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    fixed_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    valid_from = models.DateField(
        null=True,
        blank=True,
    )

    valid_until = models.DateField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
            "-id",
        ]

    def __str__(self):
        return self.name


class PriceListItem(models.Model):
    price_list = models.ForeignKey(
        PriceList,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        "inventory.Product",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    variant = models.ForeignKey(
        "inventory.ProductVariant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    custom_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )

    minimum_quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.price_list.name} - {self.product}"


class PriceListCustomer(models.Model):
    price_list = models.ForeignKey(
        PriceList,
        on_delete=models.CASCADE,
        related_name="customers",
    )

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "price_list",
                    "customer",
                ],
                name="unique_price_list_customer",
            ),
        ]

    def __str__(self):
        return f"{self.price_list.name} - {self.customer}"


class SalesReport(TimeStampedModel, BranchAware):
    report_name = models.CharField(
        max_length=120,
    )

    report_type = models.CharField(
        max_length=50,
    )

    period = models.CharField(
        max_length=30,
    )

    custom_start = models.DateField(
        null=True,
        blank=True,
    )

    custom_end = models.DateField(
        null=True,
        blank=True,
    )

    group_by = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    sales_channel = models.CharField(
        max_length=30,
        null=True,
        blank=True,
    )

    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    output_format = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        default="PDF",
    )

    include_line_items = models.BooleanField(
        default=True,
    )

    owner_team = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    email_to = models.EmailField(
        null=True,
        blank=True,
    )

    recurrence = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        default="ONCE",
    )

    status = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        default="READY",
    )
    generated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_run_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    error_message = models.TextField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
            "-id",
        ]

    def __str__(self):
        return self.report_name
