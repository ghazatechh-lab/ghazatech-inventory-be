from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from apps.common.models import TimeStampedModel, BranchAwareModel


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Expense(TimeStampedModel, BranchAwareModel):
    expense_number = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
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
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_cash_sales = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_cash_expenses = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    closing_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    register_date = models.DateField()
    closed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=30, default="OPEN")


class BankAccount(TimeStampedModel):
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    bank_name = models.CharField(max_length=150)
    account_name = models.CharField(max_length=150)
    account_number = models.CharField(max_length=100)
    iban_number = models.CharField(max_length=100, blank=True)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)


class ChartOfAccount(TimeStampedModel):
    TYPES = [
        ("ASSET", "Asset"),
        ("LIABILITY", "Liability"),
        ("EQUITY", "Equity"),
        ("INCOME", "Income / Revenue"),
        ("EXPENSE", "Expense"),
    ]

    SUB_TYPES = [
        ("CURRENT_ASSET", "Current Asset"),
        ("BANK", "Bank"),
        ("CASH", "Cash"),
        ("ACCOUNTS_RECEIVABLE", "Accounts Receivable"),
        ("INVENTORY", "Inventory"),
        ("PREPAID_EXPENSE", "Prepaid Expense"),
        ("FIXED_ASSET", "Fixed Asset"),
        ("ACCUMULATED_DEPRECIATION", "Accumulated Depreciation"),
        ("OTHER_ASSET", "Other Asset"),
        ("CURRENT_LIABILITY", "Current Liability"),
        ("ACCOUNTS_PAYABLE", "Accounts Payable"),
        ("VAT_PAYABLE", "VAT Payable"),
        ("ACCRUED_EXPENSE", "Accrued Expense"),
        ("PAYROLL_PAYABLE", "Payroll Payable"),
        ("LONG_TERM_LIABILITY", "Long-term Liability"),
        ("OTHER_LIABILITY", "Other Liability"),
        ("OWNER_EQUITY", "Owner's Equity"),
        ("RETAINED_EARNINGS", "Retained Earnings"),
        ("CURRENT_YEAR_EARNINGS", "Current Year Earnings"),
        ("SALES_REVENUE", "Sales Revenue"),
        ("SERVICE_REVENUE", "Service Revenue"),
        ("OTHER_INCOME", "Other Income"),
        ("COST_OF_GOODS_SOLD", "Cost of Goods Sold"),
        ("PAYROLL_EXPENSE", "Payroll Expense"),
        ("RENT_EXPENSE", "Rent Expense"),
        ("DEPRECIATION_EXPENSE", "Depreciation Expense"),
        ("UTILITY_EXPENSE", "Utility Expense"),
        ("BANK_CHARGE", "Bank Charges"),
        ("OTHER_EXPENSE", "Other Expense"),
    ]

    NORMAL_BALANCES = [
        ("DEBIT", "Debit"),
        ("CREDIT", "Credit"),
    ]

    TAX_TREATMENTS = [
        ("NOT_APPLICABLE", "Not Applicable"),
        ("VAT_STANDARD", "VAT Applicable — Standard 5%"),
        ("VAT_ZERO", "VAT Zero-rated"),
        ("VAT_EXEMPT", "VAT Exempt"),
        ("VAT_INPUT", "VAT Input / Recoverable"),
        ("VAT_OUTPUT", "VAT Output / Payable"),
    ]

    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        help_text="Leave blank to make this account available to all branches.",
    )
    code = models.CharField(max_length=5)
    name = models.CharField(max_length=180)
    account_type = models.CharField(max_length=20, choices=TYPES)
    sub_type = models.CharField(max_length=40, choices=SUB_TYPES, blank=True, null=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    normal_balance = models.CharField(
        max_length=10,
        choices=NORMAL_BALANCES,
        default="DEBIT",
    )
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    tax_treatment = models.CharField(
        max_length=30,
        choices=TAX_TREATMENTS,
        default="NOT_APPLICABLE",
    )
    is_active = models.BooleanField(default=True)
    lock_from_posting = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "code"],
                name="uniq_finance_account_branch_code",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(branch__isnull=True),
                name="uniq_finance_global_account_code",
            ),
        ]
        ordering = ["code"]

    @property
    def balance(self):
        return self.current_balance

    @property
    def is_global(self):
        return self.branch_id is None

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(TimeStampedModel, BranchAwareModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("POSTED", "Posted"),
        ("REVERSED", "Reversed"),
    ]
    VOUCHER_TYPES = [
        ("MANUAL", "Manual"),
        ("SALES", "Sales"),
        ("PURCHASE", "Purchase"),
        ("RECEIPT", "Receipt"),
        ("PAYMENT", "Payment"),
        ("CONTRA", "Contra"),
        ("SYSTEM", "System"),
    ]

    entry_number = models.CharField(max_length=50, unique=True)
    entry_date = models.DateField()
    voucher_type = models.CharField(
        max_length=20,
        choices=VOUCHER_TYPES,
        default="MANUAL",
    )
    reference = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    attachment = models.FileField(
        upload_to="finance/journals/",
        null=True,
        blank=True,
    )
    is_recurring_template = models.BooleanField(default=False)
    recurrence_frequency = models.CharField(max_length=30, blank=True)
    is_reversing = models.BooleanField(default=False)
    reversal_date = models.DateField(null=True, blank=True)
    approval_workflow = models.CharField(
        max_length=100,
        blank=True,
        default="ACCOUNTANT_FINANCE_MANAGER",
    )
    approver = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_approvals",
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_journals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS, default="DRAFT")
    posted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_journals",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    @property
    def total_debit(self):
        return self.lines.aggregate(v=models.Sum("debit"))["v"] or Decimal("0")

    @property
    def total_credit(self):
        return self.lines.aggregate(v=models.Sum("credit"))["v"] or Decimal("0")


class JournalLine(TimeStampedModel):
    journal = models.ForeignKey(
        JournalEntry, related_name="lines", on_delete=models.CASCADE
    )
    account = models.ForeignKey(ChartOfAccount, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    def clean(self):
        if self.debit and self.credit:
            raise ValidationError("A line cannot contain both debit and credit.")
        if not self.debit and not self.credit:
            raise ValidationError("Debit or credit is required.")


class LedgerEntry(TimeStampedModel):
    entry_number = models.CharField(max_length=50, unique=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    account = models.ForeignKey(
        ChartOfAccount, null=True, blank=True, on_delete=models.PROTECT
    )
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
    debit_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    credit_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    transaction_date = models.DateField()
    remarks = models.TextField(blank=True)


class FixedAsset(TimeStampedModel, BranchAwareModel):
    METHODS = [
        ("STRAIGHT_LINE", "Straight Line"),
        ("DECLINING", "Declining Balance"),
        ("UNITS_OF_PRODUCTION", "Units of Production"),
    ]
    START_RULES = [
        ("PURCHASE_DATE", "Date of Purchase"),
        ("NEXT_MONTH", "First Day of Next Month"),
        ("CUSTOM_DATE", "Custom Date"),
    ]

    asset_code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=100)
    purchase_date = models.DateField()
    purchase_cost = models.DecimalField(max_digits=16, decimal_places=2)

    custodian = models.CharField(max_length=150, blank=True)
    supplier_invoice_reference = models.CharField(max_length=150, blank=True)

    residual_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    useful_life_months = models.PositiveIntegerField(default=60)
    depreciation_method = models.CharField(
        max_length=30,
        choices=METHODS,
        default="STRAIGHT_LINE",
    )
    depreciation_start_rule = models.CharField(
        max_length=30,
        choices=START_RULES,
        default="PURCHASE_DATE",
    )
    depreciation_start_date = models.DateField(null=True, blank=True)
    production_capacity = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        null=True,
        blank=True,
    )
    capitalization_threshold = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=2000,
    )

    accumulated_depreciation = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    allow_branch_transfer = models.BooleanField(default=True)
    tag_retired = models.BooleanField(default=False)
    status = models.CharField(max_length=30, default="ACTIVE")
    notes = models.TextField(blank=True)

    @property
    def book_value(self):
        return max(
            Decimal("0"),
            self.purchase_cost - self.accumulated_depreciation,
        )


class TaxRate(TimeStampedModel):
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT
    )
    name = models.CharField(max_length=100)
    tax_type = models.CharField(max_length=30, default="VAT")
    rate = models.DecimalField(max_digits=6, decimal_places=3)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    tax_registration_number = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)


class Budget(TimeStampedModel, BranchAwareModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("APPROVED", "Approved"),
        ("CLOSED", "Closed"),
    ]

    PHASING_METHODS = [
        ("EVEN", "Even monthly"),
        ("SEASONAL", "Seasonal weighting"),
        ("CUSTOM", "Custom monthly amounts"),
    ]

    NOTIFY_OPTIONS = [
        ("OWNER", "Budget Owner"),
        ("FINANCE_MANAGER", "Finance Manager"),
        (
            "OWNER_FINANCE_MANAGER",
            "Budget Owner + Finance Manager",
        ),
    ]

    name = models.CharField(max_length=180)
    fiscal_year = models.PositiveIntegerField()

    account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name="budgets",
    )

    department_name = models.CharField(
        max_length=150,
        blank=True,
    )

    cost_centre = models.CharField(
        max_length=100,
        blank=True,
    )

    period_from = models.DateField()
    period_to = models.DateField()

    budget_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
    )

    actual_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )

    phasing_method = models.CharField(
        max_length=20,
        choices=PHASING_METHODS,
        default="EVEN",
    )

    monthly_phasing = models.JSONField(
        default=dict,
        blank=True,
    )

    spend_alert_enabled = models.BooleanField(
        default=True,
    )

    alert_threshold_percent = models.PositiveSmallIntegerField(
        default=90,
    )

    notify_option = models.CharField(
        max_length=40,
        choices=NOTIFY_OPTIONS,
        default="OWNER_FINANCE_MANAGER",
    )

    rolling_forecast_enabled = models.BooleanField(
        default=True,
    )

    revision_number = models.PositiveIntegerField(
        default=1,
    )

    revision_note = models.TextField(
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="DRAFT",
    )

    class Meta:
        ordering = [
            "-fiscal_year",
            "account__code",
            "id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "branch",
                    "fiscal_year",
                    "account",
                    "department_name",
                    "cost_centre",
                    "revision_number",
                ],
                name="uniq_budget_scope_revision",
            ),
        ]

    @property
    def variance(self):
        return Decimal(self.budget_amount or 0) - Decimal(self.actual_amount or 0)

    @property
    def percent_used(self):
        budget = Decimal(self.budget_amount or 0)

        if budget <= 0:
            return Decimal("0")

        return Decimal(self.actual_amount or 0) / budget * Decimal("100")

    def __str__(self):
        return f"FY {self.fiscal_year} - " f"{self.account.code} {self.account.name}"


class AccountingPeriod(TimeStampedModel):
    STATUS = [("OPEN", "Open"), ("CLOSED", "Closed"), ("LOCKED", "Locked")]
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT
    )
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS, default="OPEN")
    closed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)


class ReceivableInvoice(TimeStampedModel, BranchAwareModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
        ("OVERDUE", "Overdue"),
        ("CANCELLED", "Cancelled"),
        ("WRITTEN_OFF", "Written Off"),
    ]
    CREDIT_TERMS = [
        ("DUE_ON_RECEIPT", "Due on Receipt"),
        ("NET_7", "Net 7"),
        ("NET_15", "Net 15"),
        ("NET_30", "Net 30"),
        ("NET_45", "Net 45"),
        ("NET_60", "Net 60"),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="finance_receivable_invoices",
    )
    invoice_date = models.DateField()
    due_date = models.DateField()
    credit_terms = models.CharField(
        max_length=30,
        choices=CREDIT_TERMS,
        default="NET_30",
    )
    customer_credit_limit = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    linked_sales_invoice_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS,
        default="DRAFT",
    )
    subtotal = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    vat_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    total_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    paid_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    automatic_overdue_reminders = models.BooleanField(default=True)
    first_reminder_days_before = models.PositiveSmallIntegerField(default=7)
    repeat_reminder_days = models.PositiveSmallIntegerField(default=7)
    allow_credit_note_write_off = models.BooleanField(default=True)
    auto_post_to_ledger = models.BooleanField(default=True)
    credit_override_approved = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]

    @property
    def balance_due(self):
        return max(
            Decimal("0"),
            Decimal(self.total_amount or 0) - Decimal(self.paid_amount or 0),
        )

    def __str__(self):
        return self.invoice_number


class ReceivableInvoiceLine(TimeStampedModel):
    invoice = models.ForeignKey(
        ReceivableInvoice,
        related_name="lines",
        on_delete=models.CASCADE,
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=1,
    )
    unit_price = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    vat_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=5,
    )
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    vat_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )


class ReceivableReceipt(TimeStampedModel, BranchAwareModel):
    METHODS = [
        ("CASH", "Cash"),
        ("BANK_TRANSFER", "Bank Transfer"),
        ("CARD", "Card"),
        ("CHEQUE", "Cheque"),
        ("OTHER", "Other"),
    ]

    receipt_number = models.CharField(max_length=50, unique=True)
    invoice = models.ForeignKey(
        ReceivableInvoice,
        related_name="receipts",
        on_delete=models.PROTECT,
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="finance_receipts",
    )
    receipt_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(
        max_length=30,
        choices=METHODS,
        default="BANK_TRANSFER",
    )
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-receipt_date", "-id"]


class BankTransaction(TimeStampedModel, BranchAwareModel):
    TRANSACTION_TYPES = [
        ("RECEIPT", "Receipt"),
        ("PAYMENT", "Payment"),
        ("TRANSFER", "Transfer"),
        ("BANK_CHARGE", "Bank Charge"),
        ("ADJUSTMENT", "Adjustment"),
    ]
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="transactions"
    )
    voucher_number = models.CharField(max_length=50, unique=True)
    transaction_date = models.DateField()
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    particulars = models.CharField(max_length=255)
    receipt_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    payment_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    running_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    reference = models.CharField(max_length=120, blank=True)
    is_bank_statement = models.BooleanField(default=False)
    is_book_entry = models.BooleanField(default=True)
    reconciliation_status = models.CharField(max_length=30, default="UNMATCHED")

    class Meta:
        ordering = ["transaction_date", "id"]


class BankFundTransfer(TimeStampedModel, BranchAwareModel):
    reference_number = models.CharField(max_length=50, unique=True)
    from_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="outgoing_transfers"
    )
    to_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    transfer_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    notes = models.TextField(blank=True)
    journal = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.SET_NULL
    )


class AssetDepreciationRun(TimeStampedModel):
    STATUS = [("DRAFT", "Draft"), ("POSTED", "Posted")]
    period = models.CharField(max_length=7)
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT
    )
    run_date = models.DateField()
    total_depreciation = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    auto_post_journal = models.BooleanField(default=True)
    lock_period_after_posting = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS, default="DRAFT")
    journal = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        unique_together = [("period", "branch")]
        ordering = ["-period"]


class AssetDepreciationLine(TimeStampedModel):
    run = models.ForeignKey(
        AssetDepreciationRun, related_name="lines", on_delete=models.CASCADE
    )
    asset = models.ForeignKey(
        FixedAsset, related_name="depreciation_lines", on_delete=models.PROTECT
    )
    opening_book_value = models.DecimalField(max_digits=16, decimal_places=2)
    depreciation_amount = models.DecimalField(max_digits=16, decimal_places=2)
    closing_book_value = models.DecimalField(max_digits=16, decimal_places=2)


class AssetDisposal(TimeStampedModel, BranchAwareModel):
    METHODS = [
        ("SOLD", "Sold"),
        ("SCRAPPED", "Scrapped"),
        ("WRITTEN_OFF", "Written off / lost / damaged"),
        ("TRANSFERRED", "Transferred out"),
    ]
    asset = models.OneToOneField(
        FixedAsset, related_name="disposal", on_delete=models.PROTECT
    )
    disposal_date = models.DateField()
    disposal_method = models.CharField(max_length=30, choices=METHODS)
    sale_proceeds = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net_book_value = models.DecimalField(max_digits=16, decimal_places=2)
    gain_or_loss = models.DecimalField(max_digits=16, decimal_places=2)
    buyer_or_recipient = models.CharField(max_length=180, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    retire_tag = models.BooleanField(default=True)
    auto_post_journal = models.BooleanField(default=True)
    journal = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.SET_NULL
    )


class PayableBill(TimeStampedModel, BranchAwareModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
        ("OVERDUE", "Overdue"),
        ("CANCELLED", "Cancelled"),
    ]
    TERMS = [
        ("DUE_ON_RECEIPT", "Due on Receipt"),
        ("NET_7", "Net 7"),
        ("NET_15", "Net 15"),
        ("NET_30", "Net 30"),
        ("NET_45", "Net 45"),
        ("NET_60", "Net 60"),
    ]
    bill_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        related_name="finance_payable_bills",
        on_delete=models.PROTECT,
    )
    supplier_invoice_number = models.CharField(max_length=100)
    bill_date = models.DateField()
    due_date = models.DateField()
    payment_terms = models.CharField(max_length=30, choices=TERMS, default="NET_30")
    purchase_order_id = models.PositiveBigIntegerField(null=True, blank=True)
    grn_id = models.PositiveBigIntegerField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    withholding_tax_amount = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    apply_withholding_tax = models.BooleanField(default=False)
    withholding_tax_rate = models.DecimalField(
        max_digits=6, decimal_places=3, default=0
    )
    route_for_approval = models.BooleanField(default=True)
    approval_threshold = models.DecimalField(
        max_digits=16, decimal_places=2, default=25000
    )
    approver = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payable_bill_approvals",
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_payable_bills",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS, default="DRAFT")
    notes = models.TextField(blank=True)

    @property
    def balance_due(self):
        return max(
            Decimal("0"),
            Decimal(self.total_amount or 0) - Decimal(self.paid_amount or 0),
        )

    class Meta:
        ordering = ["-bill_date", "-id"]


class PayableBillLine(TimeStampedModel):
    bill = models.ForeignKey(
        PayableBill, related_name="lines", on_delete=models.CASCADE
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_rate = models.DecimalField(max_digits=6, decimal_places=3, default=5)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class PayablePayment(TimeStampedModel, BranchAwareModel):
    METHODS = [
        ("CASH", "Cash"),
        ("BANK_TRANSFER", "Bank Transfer"),
        ("CARD", "Card"),
        ("CHEQUE", "Cheque"),
        ("OTHER", "Other"),
    ]
    payment_number = models.CharField(max_length=50, unique=True)
    bill = models.ForeignKey(
        PayableBill, related_name="payments", on_delete=models.PROTECT
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        related_name="finance_payable_payments",
        on_delete=models.PROTECT,
    )
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(
        max_length=30, choices=METHODS, default="BANK_TRANSFER"
    )
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
