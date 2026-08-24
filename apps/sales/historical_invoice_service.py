from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.finance.models import (
    ChartOfAccount,
    LedgerEntry,
    ReceivableInvoice,
    ReceivableInvoiceLine,
)


def _decimal(value):
    return Decimal(str(value or 0))


def _has_field(model, field_name):
    return any(field.name == field_name for field in model._meta.get_fields())


def _accounts(branch):
    return ChartOfAccount.objects.filter(
        Q(branch=branch) | Q(branch__isnull=True),
        is_active=True,
        lock_from_posting=False,
    ).order_by("-branch_id", "code")


def _account(branch, sub_types, account_type=None):
    qs = _accounts(branch)
    obj = qs.filter(sub_type__in=sub_types).first()
    if obj:
        return obj
    return qs.filter(account_type=account_type).first() if account_type else None


def _increase_balance(account, amount):
    account = ChartOfAccount.objects.select_for_update().get(pk=account.pk)
    account.current_balance = _decimal(account.current_balance) + _decimal(amount)
    account.save(update_fields=["current_balance", "updated_at"])
    return account


def _receivable_number(sales_invoice):
    base = f"AR-{sales_invoice.invoice_number}"[:50]
    existing = ReceivableInvoice.objects.filter(invoice_number=base).first()
    if not existing or existing.linked_sales_invoice_id == sales_invoice.pk:
        return base
    return f"AR-HIST-{sales_invoice.pk:08d}"[:50]


def _salesperson_name(invoice):
    user = getattr(invoice, "salesperson", None)
    if not user:
        return ""
    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name) and get_full_name():
        return get_full_name()
    return (
        getattr(user, "full_name", None) or getattr(user, "username", None) or str(user)
    )


def _tax_category(item):
    treatment = str(
        getattr(item, "tax_treatment", "STANDARD_VAT") or "STANDARD_VAT"
    ).upper()
    return {
        "STANDARD_VAT": "STANDARD",
        "ZERO_RATED": "ZERO_RATED",
        "EXEMPT": "EXEMPT",
    }.get(treatment, "NON_VAT")


def _create_line(receivable, item):
    qty = _decimal(item.quantity)
    price = _decimal(item.unit_price)
    gross = qty * price
    taxable = _decimal(getattr(item, "taxable_amount", gross))
    vat = _decimal(getattr(item, "tax_amount", 0))
    total = _decimal(getattr(item, "line_total", taxable + vat))

    kwargs = {
        "invoice": receivable,
        "description": item.description
        or getattr(item.product, "product_name", "")
        or "Historical item",
        "quantity": qty,
        "unit_price": price,
    }
    optional = {
        "item_service": getattr(item.product, "product_name", "")
        or item.description
        or "Historical item",
        "discount_percent": Decimal("0"),
        "tax_category": _tax_category(item),
        "vat_rate": _decimal(
            getattr(item, "tax_rate", getattr(item, "vat_percentage", 0))
        ),
        "amount": gross,
        "discount_amount": max(Decimal("0"), gross - taxable),
        "taxable_amount": taxable,
        "vat_amount": vat,
        "line_total": total,
    }
    for name, value in optional.items():
        if _has_field(ReceivableInvoiceLine, name):
            kwargs[name] = value
    ReceivableInvoiceLine.objects.create(**kwargs)


def _ledger(receivable, account, suffix, debit=0, credit=0, remarks=""):
    account = _increase_balance(account, _decimal(debit) + _decimal(credit))
    LedgerEntry.objects.create(
        entry_number=f"{receivable.invoice_number}-{suffix}"[:50],
        branch=receivable.branch,
        account=account,
        ledger_type=account.account_type,
        transaction_type="RECEIVABLE_INVOICE",
        reference_type="ReceivableInvoice",
        reference_id=str(receivable.pk),
        debit_amount=_decimal(debit),
        credit_amount=_decimal(credit),
        balance=account.current_balance,
        transaction_date=receivable.invoice_date,
        remarks=remarks,
    )


@transaction.atomic
def create_and_post_historical_receivable(sales_invoice, user=None):
    """Post a historical SalesInvoice to accounting only, on its original date."""
    if not sales_invoice.is_historical:
        return None

    existing = (
        ReceivableInvoice.objects.select_for_update()
        .filter(linked_sales_invoice_id=sales_invoice.pk)
        .first()
    )
    if existing:
        return existing

    if not sales_invoice.branch_id or not sales_invoice.customer_id:
        raise serializers.ValidationError(
            {"accounting": "Branch and customer are required."}
        )
    if not sales_invoice.invoice_date:
        raise serializers.ValidationError(
            {"invoice_date": "Original invoice date is required."}
        )

    ar = _account(sales_invoice.branch, ["ACCOUNTS_RECEIVABLE", "AR"], "ASSET")
    revenue = _account(sales_invoice.branch, ["SALES_REVENUE", "SALES"], "INCOME")
    vat_amount = _decimal(sales_invoice.vat_amount)
    vat = (
        _account(sales_invoice.branch, ["VAT_PAYABLE", "OUTPUT_VAT"], "LIABILITY")
        if vat_amount > 0
        else None
    )

    if not ar:
        raise serializers.ValidationError(
            {
                "accounting": "Accounts Receivable account is not configured for this branch."
            }
        )
    if not revenue:
        raise serializers.ValidationError(
            {"accounting": "Sales Revenue account is not configured for this branch."}
        )
    if vat_amount > 0 and not vat:
        raise serializers.ValidationError(
            {
                "accounting": "Output VAT / VAT Payable account is not configured for this branch."
            }
        )

    total = _decimal(sales_invoice.total_amount)
    revenue_value = max(Decimal("0"), total - vat_amount)

    kwargs = {
        "invoice_number": _receivable_number(sales_invoice),
        "customer": sales_invoice.customer,
        "branch": sales_invoice.branch,
        "invoice_date": sales_invoice.invoice_date,
        "due_date": sales_invoice.due_date or sales_invoice.invoice_date,
        "linked_sales_invoice_id": sales_invoice.pk,
        "status": "DRAFT",
        "subtotal": _decimal(sales_invoice.subtotal),
        "vat_amount": vat_amount,
        "total_amount": total,
        "paid_amount": Decimal("0"),
        "notes": f"Created automatically from previous Sales Invoice {sales_invoice.invoice_number}.",
    }
    optional = {
        "credit_terms": sales_invoice.payment_terms or "NET_30",
        "customer_po_reference": sales_invoice.customer_po_number or "",
        "currency": sales_invoice.currency or "AED",
        "exchange_rate": Decimal("1"),
        "salesperson_name": _salesperson_name(sales_invoice),
        "revenue_account": revenue,
        "discount_amount": _decimal(sales_invoice.discount_amount),
        "taxable_amount": revenue_value,
        "invoice_narration": f"Previous invoice {sales_invoice.invoice_number}",
        "internal_notes": sales_invoice.historical_reference
        or "Historical invoice import",
        "auto_post_to_ledger": True,
    }
    for name, value in optional.items():
        if _has_field(ReceivableInvoice, name):
            kwargs[name] = value

    receivable = ReceivableInvoice.objects.create(**kwargs)

    for item in sales_invoice.items.select_related("product", "variant").all():
        _create_line(receivable, item)

    remarks = (
        sales_invoice.historical_reference
        or f"Previous invoice {sales_invoice.invoice_number}"
    )
    _ledger(receivable, ar, "AR", debit=total, remarks=remarks)
    if revenue_value > 0:
        _ledger(receivable, revenue, "REV", credit=revenue_value, remarks=remarks)
    if vat and vat_amount > 0:
        _ledger(receivable, vat, "VAT", credit=vat_amount, remarks=f"VAT - {remarks}")

    receivable.status = "OPEN"
    fields = ["status", "updated_at"]
    if _has_field(ReceivableInvoice, "posted_at"):
        receivable.posted_at = timezone.now()
        fields.append("posted_at")
    if user and _has_field(ReceivableInvoice, "posted_by"):
        receivable.posted_by = user
        fields.append("posted_by")
    receivable.save(update_fields=fields)
    return receivable
