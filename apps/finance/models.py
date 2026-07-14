from django.db import models
from apps.common.models import TimeStampedModel, BranchAwareModel


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)


class Expense(TimeStampedModel, BranchAwareModel):
    expense_number = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=30)
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True, on_delete=models.SET_NULL
    )
    attachment = models.FileField(upload_to="expenses/", null=True, blank=True)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_expenses",
    )


class CashRegister(TimeStampedModel):
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cash_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cash_expenses = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    register_date = models.DateField()
    closed_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=30, default="OPEN")


class BankAccount(TimeStampedModel):
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    bank_name = models.CharField(max_length=150)
    account_name = models.CharField(max_length=150)
    account_number = models.CharField(max_length=100)
    iban_number = models.CharField(max_length=100, blank=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)


class LedgerEntry(TimeStampedModel):
    entry_number = models.CharField(max_length=50, unique=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    ledger_type = models.CharField(max_length=20)
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.PROTECT
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True, on_delete=models.PROTECT
    )
    transaction_type = models.CharField(max_length=50)
    reference_type = models.CharField(max_length=100)
    reference_id = models.CharField(max_length=100)
    debit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transaction_date = models.DateField()
    remarks = models.TextField(blank=True)
