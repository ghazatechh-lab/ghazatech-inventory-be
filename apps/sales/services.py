from django.db import transaction
from .models import SalesInvoice, SalesPayment
from apps.inventory.services import adjust_stock
from apps.finance.services import record_customer_ledger
from apps.audit_logs.services import log_action


@transaction.atomic
def confirm_invoice(invoice, user):
    if invoice.is_confirmed:
        return invoice
    for item in invoice.items.select_related("product"):
        adjust_stock(
            product=item.product,
            branch=invoice.branch,
            quantity=-item.quantity,
            movement_type="SALE",
            performed_by=user,
            reference_type="SalesInvoice",
            reference_id=invoice.id,
        )
    invoice.is_confirmed = True
    invoice.balance_due = invoice.total_amount - invoice.paid_amount
    invoice.save(update_fields=["is_confirmed", "balance_due", "updated_at"])
    record_customer_ledger(invoice, invoice.total_amount, "Invoice")
    log_action(
        user,
        invoice.branch,
        "sales",
        "Invoice Confirmed",
        f"Invoice {invoice.invoice_number} confirmed",
        invoice,
    )
    return invoice


@transaction.atomic
def add_payment(payment, user):
    invoice = payment.invoice
    if invoice:
        invoice.paid_amount += payment.amount
        invoice.balance_due = max(0, invoice.total_amount - invoice.paid_amount)
        invoice.payment_status = "PAID" if invoice.balance_due == 0 else "PARTIAL"
        invoice.save(
            update_fields=["paid_amount", "balance_due", "payment_status", "updated_at"]
        )
    record_customer_ledger(payment, payment.amount, "Payment", credit=True)
    return payment
