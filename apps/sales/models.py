from django.db import models
from apps.common.models import TimeStampedModel, BranchAwareModel


class Quotation(TimeStampedModel, BranchAwareModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("EXPIRED", "Expired"),
        ("CONVERTED", "Converted to Invoice"),
    ]
    quotation_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT)
    salesperson = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL, related_name="quotations"
    )
    quotation_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS, default="DRAFT")
    notes = models.TextField(blank=True)
    terms_and_conditions = models.TextField(blank=True)


class QuotationItem(models.Model):
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)


class SalesInvoice(TimeStampedModel, BranchAwareModel):
    TYPES = [
        ("QUOTATION", "Quotation Sale"),
        ("DIRECT", "Direct Sale"),
        ("WALKIN", "Walk-in Sale"),
    ]
    PAY = [
        ("PAID", "Paid"),
        ("PARTIAL", "Partially Paid"),
        ("UNPAID", "Unpaid"),
        ("OVERDUE", "Overdue"),
        ("CANCELLED", "Cancelled"),
    ]
    DELIVERY = [
        ("PENDING", "Pending"),
        ("PACKED", "Packed"),
        ("OUT", "Out for Delivery"),
        ("DELIVERED", "Delivered"),
        ("RETURNED", "Returned"),
        ("CANCELLED", "Cancelled"),
    ]
    invoice_number = models.CharField(max_length=50, unique=True)
    quotation = models.OneToOneField(
        Quotation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice",
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT)
    salesperson = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="sales_invoices",
    )
    sale_type = models.CharField(max_length=20, choices=TYPES, default="DIRECT")
    invoice_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=PAY, default="UNPAID")
    delivery_status = models.CharField(
        max_length=20, choices=DELIVERY, default="PENDING"
    )
    notes = models.TextField(blank=True)
    is_confirmed = models.BooleanField(default=False)


class SalesInvoiceItem(models.Model):
    invoice = models.ForeignKey(
        SalesInvoice, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)


class SalesCreditNote(TimeStampedModel, BranchAwareModel):
    credit_note_number = models.CharField(max_length=50, unique=True)
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.PROTECT)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT)
    reason = models.CharField(max_length=120)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default="DRAFT")
    notes = models.TextField(blank=True)


class SalesPayment(TimeStampedModel, BranchAwareModel):
    receipt_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT)
    invoice = models.ForeignKey(
        SalesInvoice,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments",
    )
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=30)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)
    received_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
