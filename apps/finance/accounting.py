from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import ChartOfAccount, JournalEntry, JournalLine, LedgerEntry


CORE_ACCOUNTS = [
    {
        "code": "10000",
        "name": "Cash on Hand",
        "account_type": "ASSET",
        "sub_type": "CASH",
        "normal_balance": "DEBIT",
    },
    {
        "code": "10100",
        "name": "Bank Control Account",
        "account_type": "ASSET",
        "sub_type": "BANK",
        "normal_balance": "DEBIT",
    },
    {
        "code": "11000",
        "name": "Accounts Receivable",
        "account_type": "ASSET",
        "sub_type": "ACCOUNTS_RECEIVABLE",
        "normal_balance": "DEBIT",
    },
    {
        "code": "12000",
        "name": "Inventory",
        "account_type": "ASSET",
        "sub_type": "INVENTORY",
        "normal_balance": "DEBIT",
    },
    {
        "code": "13000",
        "name": "Input VAT Recoverable",
        "account_type": "ASSET",
        "sub_type": "CURRENT_ASSET",
        "normal_balance": "DEBIT",
        "tax_treatment": "VAT_INPUT",
    },
    {
        "code": "20000",
        "name": "Accounts Payable",
        "account_type": "LIABILITY",
        "sub_type": "ACCOUNTS_PAYABLE",
        "normal_balance": "CREDIT",
    },
    {
        "code": "21000",
        "name": "Output VAT Payable",
        "account_type": "LIABILITY",
        "sub_type": "VAT_PAYABLE",
        "normal_balance": "CREDIT",
        "tax_treatment": "VAT_OUTPUT",
    },
    {
        "code": "30000",
        "name": "Owner Capital",
        "account_type": "EQUITY",
        "sub_type": "OWNER_EQUITY",
        "normal_balance": "CREDIT",
    },
    {
        "code": "31000",
        "name": "Retained Earnings",
        "account_type": "EQUITY",
        "sub_type": "RETAINED_EARNINGS",
        "normal_balance": "CREDIT",
    },
    {
        "code": "40000",
        "name": "Sales Revenue",
        "account_type": "INCOME",
        "sub_type": "SALES_REVENUE",
        "normal_balance": "CREDIT",
    },
    {
        "code": "50000",
        "name": "Cost of Goods Sold",
        "account_type": "EXPENSE",
        "sub_type": "COST_OF_GOODS_SOLD",
        "normal_balance": "DEBIT",
    },
    {
        "code": "51000",
        "name": "Operating / Purchase Expense",
        "account_type": "EXPENSE",
        "sub_type": "OTHER_EXPENSE",
        "normal_balance": "DEBIT",
    },
]


def ensure_core_accounts():
    """Create the global core Chart of Accounts. Safe to run repeatedly."""
    created = []
    for definition in CORE_ACCOUNTS:
        defaults = {
            **definition,
            "tax_treatment": definition.get("tax_treatment", "NOT_APPLICABLE"),
            "opening_balance": Decimal("0.00"),
            "current_balance": Decimal("0.00"),
            "is_active": True,
            "lock_from_posting": False,
            "notes": "System core account. Created by backend accounting setup.",
        }
        code = defaults.pop("code")
        account, was_created = ChartOfAccount.objects.get_or_create(
            branch=None,
            code=code,
            defaults=defaults,
        )
        if was_created:
            created.append(account)
    return created


def _account(branch, *, code=None, sub_type=None, tax_treatment=None):
    ensure_core_accounts()
    qs = ChartOfAccount.objects.filter(
        Q(branch=branch) | Q(branch__isnull=True),
        is_active=True,
        lock_from_posting=False,
    )
    if code:
        qs = qs.filter(code=code)
    if sub_type:
        qs = qs.filter(sub_type=sub_type)
    if tax_treatment:
        qs = qs.filter(tax_treatment=tax_treatment)
    account = qs.order_by("-branch_id", "code").first()
    if not account:
        identity = code or sub_type or tax_treatment or "requested"
        raise ValueError(f"Accounting account {identity} is not configured.")
    return account


def _payment_account(branch, payment_method, bank_account=None, cash_register=None):
    method = str(payment_method or "").upper()
    if method in {"CASH", "PETTY_CASH"}:
        if not cash_register:
            raise ValueError("Cash Register is required for a cash accounting entry.")
        return _account(branch, code="10000")

    if method in {"BANK_TRANSFER", "CHEQUE", "CARD"}:
        if not bank_account:
            raise ValueError("Bank Account is required for this accounting entry.")
        if getattr(bank_account, "chart_account_id", None):
            return bank_account.chart_account
        return _account(branch, code="10100")

    # OTHER payments use the bank control account when a bank is selected,
    # otherwise cash control. This keeps the journal balanced but still makes
    # the source visible in the document itself.
    if bank_account:
        return bank_account.chart_account or _account(branch, code="10100")
    if cash_register:
        return _account(branch, code="10000")
    raise ValueError("Select a Bank Account or Cash Register for the payment.")


def _next_system_number():
    prefix = timezone.now().strftime("SYS-%Y%m-")
    last = (
        JournalEntry.objects.select_for_update()
        .filter(entry_number__startswith=prefix)
        .order_by("-entry_number")
        .values_list("entry_number", flat=True)
        .first()
    )
    sequence = 1
    if last:
        try:
            sequence = int(last.rsplit("-", 1)[-1]) + 1
        except (TypeError, ValueError):
            sequence = JournalEntry.objects.filter(entry_number__startswith=prefix).count() + 1
    candidate = f"{prefix}{sequence:05d}"
    while JournalEntry.objects.filter(entry_number=candidate).exists():
        sequence += 1
        candidate = f"{prefix}{sequence:05d}"
    return candidate


def _move_account(account, debit, credit):
    debit = Decimal(str(debit or 0))
    credit = Decimal(str(credit or 0))
    movement = debit - credit
    if account.normal_balance == "CREDIT":
        movement = credit - debit
    account.current_balance = Decimal(account.current_balance or 0) + movement
    account.save(update_fields=["current_balance", "updated_at"])


def _post_system_journal(*, branch, date, reference, description, lines, user=None):
    """Post one balanced idempotent system journal and update the GL."""
    existing = JournalEntry.objects.filter(
        source="SYSTEM",
        reference=reference,
        status="POSTED",
    ).first()
    if existing:
        return existing

    total_debit = sum((Decimal(str(line.get("debit", 0) or 0)) for line in lines), Decimal("0"))
    total_credit = sum((Decimal(str(line.get("credit", 0) or 0)) for line in lines), Decimal("0"))
    if total_debit <= 0 or total_debit != total_credit:
        raise ValueError(
            f"System journal is not balanced: debit={total_debit}, credit={total_credit}."
        )

    journal = JournalEntry.objects.create(
        entry_number=_next_system_number(),
        entry_date=date or timezone.localdate(),
        document_date=date or timezone.localdate(),
        branch=branch,
        voucher_type="ADJUSTMENT",
        source="SYSTEM",
        reference=reference,
        description=description,
        currency="AED",
        exchange_rate=Decimal("1"),
        status="POSTED",
        posted_by=user if getattr(user, "is_authenticated", False) else None,
        posted_at=timezone.now(),
        created_by=user if getattr(user, "is_authenticated", False) else None,
        updated_by=user if getattr(user, "is_authenticated", False) else None,
    )

    for index, source_line in enumerate(lines, start=1):
        debit = Decimal(str(source_line.get("debit", 0) or 0))
        credit = Decimal(str(source_line.get("credit", 0) or 0))
        account = source_line["account"]
        line = JournalLine.objects.create(
            journal=journal,
            account=account,
            description=source_line.get("description", description),
            debit=debit,
            credit=credit,
        )
        _move_account(account, debit, credit)
        LedgerEntry.objects.create(
            entry_number=f"{journal.entry_number}-{index}",
            branch=branch,
            account=account,
            ledger_type=account.account_type,
            transaction_type="SYSTEM_JOURNAL",
            reference_type="JournalEntry",
            reference_id=str(journal.id),
            debit_amount=debit,
            credit_amount=credit,
            balance=account.current_balance,
            transaction_date=journal.entry_date,
            remarks=line.description,
        )
    return journal


def _reverse_reference(reference, *, user=None, reason="System reversal"):
    original = JournalEntry.objects.filter(
        source="SYSTEM",
        reference=reference,
        status="POSTED",
    ).prefetch_related("lines__account").first()
    if not original:
        return None
    reversal_reference = f"{reference}:REV:{original.pk}"
    if JournalEntry.objects.filter(source="SYSTEM", reference=reversal_reference, status="POSTED").exists():
        return None
    lines = [
        {
            "account": line.account,
            "debit": line.credit,
            "credit": line.debit,
            "description": f"Reversal: {line.description or original.description}",
        }
        for line in original.lines.all()
    ]
    reversal = _post_system_journal(
        branch=original.branch,
        date=timezone.localdate(),
        reference=reversal_reference,
        description=reason,
        lines=lines,
        user=user,
    )
    original.status = "REVERSED"
    original.save(update_fields=["status", "updated_at"])
    return reversal


def _update_money_source(*, amount, direction, bank_account=None, cash_register=None, cash_bucket=None):
    amount = Decimal(str(amount or 0))
    if amount <= 0:
        return
    if bank_account:
        delta = amount if direction == "IN" else -amount
        bank_account.current_balance = Decimal(bank_account.current_balance or 0) + delta
        bank_account.save(update_fields=["current_balance", "updated_at"])
    if cash_register:
        if cash_bucket == "SALES":
            cash_register.total_cash_sales = Decimal(cash_register.total_cash_sales or 0) + amount
        elif cash_bucket == "EXPENSE":
            cash_register.total_cash_expenses = Decimal(cash_register.total_cash_expenses or 0) + amount
        cash_register.closing_balance = (
            Decimal(cash_register.opening_balance or 0)
            + Decimal(cash_register.total_cash_sales or 0)
            - Decimal(cash_register.total_cash_expenses or 0)
        )
        cash_register.save(update_fields=[
            "total_cash_sales", "total_cash_expenses", "closing_balance", "updated_at"
        ])


@transaction.atomic
def post_supplier_bill(bill, user=None):
    reference = f"SUPPLIER_BILL:{bill.pk}"
    inventory = _account(bill.branch, code="12000")
    ap = _account(bill.branch, code="20000")
    vat = Decimal(str(bill.vat_amount or 0))
    total = Decimal(str(bill.total_amount or 0))
    net = total - vat
    lines = [
        {"account": inventory, "debit": net, "credit": 0, "description": f"Inventory - {bill.bill_number}"},
    ]
    if vat > 0:
        lines.append({
            "account": _account(bill.branch, code="13000"),
            "debit": vat,
            "credit": 0,
            "description": f"Input VAT - {bill.bill_number}",
        })
    lines.append({"account": ap, "debit": 0, "credit": total, "description": f"Supplier payable - {bill.bill_number}"})
    return _post_system_journal(
        branch=bill.branch,
        date=bill.bill_date,
        reference=reference,
        description=f"Supplier Bill {bill.bill_number}",
        lines=lines,
        user=user,
    )


@transaction.atomic
def post_supplier_payment(payment, user=None):
    reference = f"SUPPLIER_PAYMENT:{payment.pk}"
    ap = _account(payment.branch, code="20000")
    money = _payment_account(
        payment.branch,
        payment.payment_method,
        bank_account=payment.bank_account,
        cash_register=payment.cash_register,
    )
    amount = Decimal(str(payment.amount or 0))
    already_posted = JournalEntry.objects.filter(
        source="SYSTEM", reference=reference, status="POSTED"
    ).exists()
    journal = _post_system_journal(
        branch=payment.branch,
        date=payment.payment_date,
        reference=reference,
        description=f"Supplier Payment {payment.payment_number}",
        lines=[
            {"account": ap, "debit": amount, "credit": 0, "description": f"Reduce supplier payable - {payment.payment_number}"},
            {"account": money, "debit": 0, "credit": amount, "description": f"Payment source - {payment.payment_number}"},
        ],
        user=user,
    )
    if not already_posted:
        _update_money_source(
            amount=amount,
            direction="OUT",
            bank_account=payment.bank_account,
            cash_register=payment.cash_register,
            cash_bucket="EXPENSE",
        )
    return journal


@transaction.atomic
def post_sales_invoice(invoice, user=None):
    reference = f"SALES_INVOICE:{invoice.pk}"
    ar = _account(invoice.branch, code="11000")
    sales = _account(invoice.branch, code="40000")
    total = Decimal(str(invoice.total_amount or 0))
    vat = Decimal(str(invoice.vat_amount or 0))
    revenue = total - vat
    lines = [
        {"account": ar, "debit": total, "credit": 0, "description": f"Customer receivable - {invoice.invoice_number}"},
        {"account": sales, "debit": 0, "credit": revenue, "description": f"Sales revenue - {invoice.invoice_number}"},
    ]
    if vat > 0:
        lines.append({
            "account": _account(invoice.branch, code="21000"),
            "debit": 0,
            "credit": vat,
            "description": f"Output VAT - {invoice.invoice_number}",
        })
    return _post_system_journal(
        branch=invoice.branch,
        date=invoice.invoice_date,
        reference=reference,
        description=f"Sales Invoice {invoice.invoice_number}",
        lines=lines,
        user=user,
    )


@transaction.atomic
def repost_sales_invoice(invoice, user=None):
    reference = f"SALES_INVOICE:{invoice.pk}"
    existing = JournalEntry.objects.filter(source="SYSTEM", reference=reference, status="POSTED").exists()
    if existing:
        _reverse_reference(reference, user=user, reason=f"Invoice amendment {invoice.invoice_number}")
    return post_sales_invoice(invoice, user=user)


@transaction.atomic
def reverse_sales_invoice(invoice, user=None):
    return _reverse_reference(
        f"SALES_INVOICE:{invoice.pk}",
        user=user,
        reason=f"Void Sales Invoice {invoice.invoice_number}",
    )


@transaction.atomic
def post_sales_payment(payment, user=None):
    reference = f"SALES_PAYMENT:{payment.pk}"
    money = _payment_account(
        payment.branch,
        payment.payment_method,
        bank_account=payment.bank_account,
        cash_register=payment.cash_register,
    )
    ar = _account(payment.branch, code="11000")
    amount = Decimal(str(payment.amount or 0))
    already_posted = JournalEntry.objects.filter(
        source="SYSTEM", reference=reference, status="POSTED"
    ).exists()
    journal = _post_system_journal(
        branch=payment.branch,
        date=payment.payment_date,
        reference=reference,
        description=f"Customer Payment {payment.payment_number}",
        lines=[
            {"account": money, "debit": amount, "credit": 0, "description": f"Payment received - {payment.payment_number}"},
            {"account": ar, "debit": 0, "credit": amount, "description": f"Reduce receivable - {payment.payment_number}"},
        ],
        user=user,
    )
    if not already_posted:
        _update_money_source(
            amount=amount,
            direction="IN",
            bank_account=payment.bank_account,
            cash_register=payment.cash_register,
            cash_bucket="SALES",
        )
    return journal


@transaction.atomic
def post_purchase_expense(expense, user=None):
    reference = f"PURCHASE_EXPENSE:{expense.pk}"
    expense_account = _account(expense.branch, code="51000")
    money = _payment_account(
        expense.branch,
        expense.payment_method,
        bank_account=expense.bank_account,
        cash_register=expense.cash_register,
    )
    amount = Decimal(str(expense.amount or 0))
    already_posted = JournalEntry.objects.filter(
        source="SYSTEM", reference=reference, status="POSTED"
    ).exists()
    journal = _post_system_journal(
        branch=expense.branch,
        date=expense.expense_date,
        reference=reference,
        description=f"Purchase Expense {expense.expense_number}",
        lines=[
            {"account": expense_account, "debit": amount, "credit": 0, "description": expense.description or expense.expense_number},
            {"account": money, "debit": 0, "credit": amount, "description": f"Expense payment - {expense.expense_number}"},
        ],
        user=user,
    )
    if not already_posted:
        _update_money_source(
            amount=amount,
            direction="OUT",
            bank_account=expense.bank_account,
            cash_register=expense.cash_register,
            cash_bucket="EXPENSE",
        )
    return journal
