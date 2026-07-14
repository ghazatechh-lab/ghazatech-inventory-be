from django.utils import timezone
from .models import LedgerEntry


def record_customer_ledger(obj, amount, transaction_type, credit=False):
    c = obj.customer
    prev = (
        LedgerEntry.objects.filter(customer=c, ledger_type="CUSTOMER")
        .order_by("-id")
        .first()
    )
    bal = (prev.balance if prev else c.opening_balance) + (
        -amount if credit else amount
    )
    return LedgerEntry.objects.create(
        entry_number=f"LE-{timezone.now():%Y%m%d%H%M%S%f}",
        branch=obj.branch,
        ledger_type="CUSTOMER",
        customer=c,
        transaction_type=transaction_type,
        reference_type=obj.__class__.__name__,
        reference_id=str(obj.id),
        debit_amount=0 if credit else amount,
        credit_amount=amount if credit else 0,
        balance=bal,
        transaction_date=timezone.localdate(),
    )
