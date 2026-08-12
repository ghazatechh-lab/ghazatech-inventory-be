from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
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
    ACCOUNT_TYPES = [
        ("BANK", "Bank"),
        ("CASH", "Cash"),
    ]

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
    )

    bank_name = models.CharField(
        max_length=150,
        blank=True,
    )

    account_name = models.CharField(
        max_length=150,
    )

    account_number = models.CharField(
        max_length=100,
        blank=True,
    )

    iban_number = models.CharField(
        max_length=100,
        blank=True,
    )

    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPES,
        default="BANK",
    )

    currency = models.CharField(
        max_length=3,
        default="AED",
    )

    chart_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bank_cash_accounts",
    )

    opening_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    current_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    statement_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    last_reconciled_date = models.DateField(
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )


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
        ("REJECTED", "Rejected"),
        ("POSTED", "Posted"),
        ("REVERSED", "Reversed"),
    ]

    JOURNAL_TYPES = [
        ("MANUAL", "Manual Journal"),
        ("ADJUSTMENT", "Adjustment"),
        ("OPENING_BALANCE", "Opening Balance"),
        ("ACCRUAL", "Accrual"),
        ("YEAR_END", "Year End"),
        ("REVERSAL", "Reversal"),
    ]

    SOURCES = [
        ("MANUAL", "Manual"),
        ("SYSTEM", "System-generated"),
    ]

    PRIORITIES = [
        ("NORMAL", "Normal"),
        ("HIGH", "High"),
        ("URGENT", "Urgent"),
    ]

    RECURRENCE_FREQUENCIES = [
        ("MONTHLY", "Monthly"),
        ("QUARTERLY", "Quarterly"),
        ("YEARLY", "Yearly"),
    ]

    entry_number = models.CharField(max_length=50, unique=True)
    entry_date = models.DateField()
    document_date = models.DateField(null=True, blank=True)

    voucher_type = models.CharField(
        max_length=30,
        choices=JOURNAL_TYPES,
        default="MANUAL",
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCES,
        default="MANUAL",
    )

    reference = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    currency = models.CharField(max_length=3, default="AED")
    exchange_rate = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        default=1,
    )

    # Kept for backward compatibility. New UI uses JournalAttachment.
    attachment = models.FileField(
        upload_to="finance/journals/",
        null=True,
        blank=True,
    )

    is_recurring_template = models.BooleanField(default=False)
    recurrence_frequency = models.CharField(
        max_length=30,
        choices=RECURRENCE_FREQUENCIES,
        blank=True,
    )
    recurrence_start_date = models.DateField(null=True, blank=True)
    recurrence_end_date = models.DateField(null=True, blank=True)

    is_reversing = models.BooleanField(default=False)
    reversal_date = models.DateField(null=True, blank=True)
    reversal_narration = models.CharField(max_length=255, blank=True)

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
    approval_priority = models.CharField(
        max_length=20,
        choices=PRIORITIES,
        default="NORMAL",
    )
    approval_comments = models.TextField(blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_journals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_journals",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    status = models.CharField(
        max_length=30,
        choices=STATUS,
        default="DRAFT",
    )

    posted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_journals",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    reversed_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reversal_entries",
    )

    class Meta:
        ordering = ["-entry_date", "-id"]

    @property
    def total_debit(self):
        return self.lines.aggregate(v=models.Sum("debit"))["v"] or Decimal("0")

    @property
    def total_credit(self):
        return self.lines.aggregate(v=models.Sum("credit"))["v"] or Decimal("0")

    @property
    def difference(self):
        return self.total_debit - self.total_credit

    @property
    def is_balanced(self):
        return self.total_debit > 0 and self.total_debit == self.total_credit

    def __str__(self):
        return self.entry_number


class JournalLine(TimeStampedModel):
    journal = models.ForeignKey(
        JournalEntry,
        related_name="lines",
        on_delete=models.CASCADE,
    )
    account = models.ForeignKey(ChartOfAccount, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True)
    cost_center = models.CharField(max_length=100, blank=True)
    project = models.CharField(max_length=100, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    def clean(self):
        if self.debit and self.credit:
            raise ValidationError("A line cannot contain both debit and credit.")
        if not self.debit and not self.credit:
            raise ValidationError("Debit or credit is required.")


class JournalAttachment(TimeStampedModel):
    journal = models.ForeignKey(
        JournalEntry,
        related_name="attachments",
        on_delete=models.CASCADE,
    )
    file = models.FileField(upload_to="finance/journals/supporting/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_attachments",
    )

    def __str__(self):
        return self.original_name or self.file.name


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
    STATUS = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("ACTIVE", "Active"),
        ("UNDER_MAINTENANCE", "Under Maintenance"),
        ("FULLY_DEPRECIATED", "Fully Depreciated"),
        ("DISPOSED", "Disposed"),
    ]
    METHODS = [
        ("STRAIGHT_LINE", "Straight Line"),
        ("DECLINING_BALANCE", "Declining Balance"),
        ("UNITS_OF_PRODUCTION", "Units of Production"),
        ("NO_DEPRECIATION", "No Depreciation"),
    ]

    asset_tag = models.CharField(max_length=50, unique=True)
    asset_name = models.CharField(max_length=180)
    category = models.CharField(max_length=120)
    asset_class = models.CharField(max_length=120, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    barcode = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)

    acquisition_type = models.CharField(max_length=30, default="PURCHASED")
    purchase_date = models.DateField()
    capitalization_date = models.DateField(null=True, blank=True)
    placed_in_service_date = models.DateField(null=True, blank=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True, on_delete=models.PROTECT
    )
    supplier_invoice = models.CharField(max_length=120, blank=True)
    purchase_order = models.CharField(max_length=120, blank=True)
    goods_receipt = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=3, default="AED")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    acquisition_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    additional_capitalized_cost = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )

    depreciation_method = models.CharField(
        max_length=30, choices=METHODS, default="STRAIGHT_LINE"
    )
    useful_life_months = models.PositiveIntegerField(default=36)
    residual_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    depreciation_start_date = models.DateField(null=True, blank=True)
    depreciation_frequency = models.CharField(max_length=20, default="MONTHLY")
    proration_convention = models.CharField(max_length=30, default="DAILY")
    tax_depreciation_method = models.CharField(max_length=30, default="SAME_AS_BOOK")
    depreciation_book = models.CharField(max_length=30, default="CORPORATE")
    depreciate_asset = models.BooleanField(default=True)
    allow_impairment = models.BooleanField(default=True)

    fixed_asset_account = models.ForeignKey(
        "finance.ChartOfAccount",
        on_delete=models.PROTECT,
        related_name="fixed_asset_cost_assets",
        null=True,
        blank=True,
    )
    accumulated_depreciation_account = models.ForeignKey(
        "finance.ChartOfAccount",
        on_delete=models.PROTECT,
        related_name="fixed_asset_accumulated_assets",
        blank=True,
        null=True,
    )
    depreciation_expense_account = models.ForeignKey(
        "finance.ChartOfAccount",
        on_delete=models.PROTECT,
        related_name="fixed_asset_expense_assets",
        blank=True,
        null=True,
    )
    disposal_gain_loss_account = models.ForeignKey(
        "finance.ChartOfAccount",
        on_delete=models.PROTECT,
        related_name="fixed_asset_disposal_assets",
        blank=True,
        null=True,
    )

    cost_center = models.CharField(max_length=120, blank=True)
    project = models.CharField(max_length=120, blank=True)
    financial_dimension = models.CharField(max_length=120, blank=True)

    location = models.CharField(max_length=180, blank=True, null=True)
    department = models.CharField(max_length=180, blank=True, null=True)
    custodian = models.CharField(max_length=180, blank=True, null=True)
    condition = models.CharField(max_length=30, default="NEW")
    assigned_date = models.DateField(null=True, blank=True)
    physical_verification_date = models.DateField(null=True, blank=True)
    insurance_policy_number = models.CharField(max_length=120, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)

    warranty_start = models.DateField(null=True, blank=True)
    warranty_expiry = models.DateField(null=True, blank=True)
    maintenance_frequency = models.CharField(max_length=30, default="NOT_REQUIRED")
    next_service_date = models.DateField(null=True, blank=True)
    service_vendor = models.CharField(max_length=180, blank=True)
    warranty_reference = models.CharField(max_length=120, blank=True)
    maintenance_notes = models.TextField(blank=True)

    status = models.CharField(max_length=30, choices=STATUS, default="DRAFT")
    accumulated_depreciation = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    approver = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fixed_asset_approvals",
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_fixed_assets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_fixed_assets",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    capitalized_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="capitalized_fixed_assets",
    )
    capitalized_at = models.DateTimeField(null=True, blank=True)

    @property
    def capitalized_cost(self):
        return Decimal(self.acquisition_cost or 0) + Decimal(
            self.additional_capitalized_cost or 0
        )

    @property
    def net_book_value(self):
        return max(
            Decimal("0"),
            self.capitalized_cost - Decimal(self.accumulated_depreciation or 0),
        )


class FixedAssetAttachment(TimeStampedModel):
    asset = models.ForeignKey(
        FixedAsset, related_name="attachments", on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="finance/fixed-assets/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )


class FixedAssetDepreciation(TimeStampedModel, BranchAwareModel):
    asset = models.ForeignKey(
        FixedAsset, related_name="depreciation_rows", on_delete=models.PROTECT
    )
    period = models.CharField(max_length=7)
    opening_nbv = models.DecimalField(max_digits=16, decimal_places=2)
    depreciation_amount = models.DecimalField(max_digits=16, decimal_places=2)
    closing_nbv = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, default="PENDING")
    journal_reference = models.CharField(max_length=80, blank=True)


class FixedAssetTransfer(TimeStampedModel, BranchAwareModel):
    transfer_number = models.CharField(max_length=50, unique=True)
    asset = models.ForeignKey(
        FixedAsset, related_name="transfers", on_delete=models.PROTECT
    )
    transfer_date = models.DateField(default=timezone.localdate)
    from_location = models.CharField(max_length=180, blank=True)
    to_location = models.CharField(max_length=180)
    from_custodian = models.CharField(max_length=180, blank=True)
    to_custodian = models.CharField(max_length=180)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=30, default="PENDING_APPROVAL")
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )


class FixedAssetMaintenance(TimeStampedModel, BranchAwareModel):
    job_number = models.CharField(max_length=50, unique=True)
    asset = models.ForeignKey(
        FixedAsset, related_name="maintenance_jobs", on_delete=models.PROTECT
    )
    maintenance_type = models.CharField(max_length=80)
    scheduled_date = models.DateField()
    vendor_technician = models.CharField(max_length=180, blank=True)
    estimated_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    downtime = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=30, default="SCHEDULED")
    next_service_date = models.DateField(null=True, blank=True)


class FixedAssetDisposal(TimeStampedModel, BranchAwareModel):
    disposal_number = models.CharField(max_length=50, unique=True)
    asset = models.ForeignKey(
        FixedAsset, related_name="disposals", on_delete=models.PROTECT
    )
    disposal_date = models.DateField()
    disposal_method = models.CharField(max_length=40)
    original_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    accumulated_depreciation = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    net_book_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    proceeds = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    gain_loss = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=30, default="PENDING_APPROVAL")
    journal_reference = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)


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


class VatSettings(TimeStampedModel):
    RETURN_FREQUENCIES = [
        ("MONTHLY", "Monthly"),
        ("QUARTERLY", "Quarterly"),
    ]

    company_name = models.CharField(
        max_length=180,
        default="Ghaza Computer TR LLC",
    )
    company_trn = models.CharField(
        max_length=50,
        blank=True,
    )
    registration_country = models.CharField(
        max_length=100,
        default="United Arab Emirates",
    )
    return_frequency = models.CharField(
        max_length=20,
        choices=RETURN_FREQUENCIES,
        default="QUARTERLY",
    )

    output_vat_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vat_settings_output_accounts",
    )
    input_vat_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vat_settings_input_accounts",
    )
    vat_payable_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vat_settings_payable_accounts",
    )

    class Meta:
        verbose_name = "VAT Setting"
        verbose_name_plural = "VAT Settings"

    def __str__(self):
        return self.company_name


class VatReturn(TimeStampedModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("VALIDATED", "Validated"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("FILED", "Filed"),
        ("PAID", "Paid"),
    ]

    PAYMENT_STATUS = [
        ("NOT_PAID", "Not Paid"),
        ("SCHEDULED", "Scheduled"),
        ("PAID", "Paid"),
    ]

    RETURN_TYPES = [
        ("VAT201", "VAT 201 — Regular Return"),
        ("AMENDED", "Amended Return"),
    ]

    RETURN_FREQUENCIES = [
        ("MONTHLY", "Monthly"),
        ("QUARTERLY", "Quarterly"),
    ]

    company_name = models.CharField(
        max_length=180,
        default="Ghaza Computer TR LLC",
    )
    trn = models.CharField(
        max_length=50,
        blank=True,
    )
    return_type = models.CharField(
        max_length=20,
        choices=RETURN_TYPES,
        default="VAT201",
    )
    return_frequency = models.CharField(
        max_length=20,
        choices=RETURN_FREQUENCIES,
        default="QUARTERLY",
    )

    period_from = models.DateField()
    period_to = models.DateField()
    filing_due_date = models.DateField(
        null=True,
        blank=True,
    )

    branch_scope = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vat_returns",
    )

    output_vat = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    input_vat = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    prior_period_credit = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    net_vat_payable = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )

    total_transactions = models.PositiveIntegerField(
        default=0,
    )
    valid_transactions = models.PositiveIntegerField(
        default=0,
    )
    warnings_count = models.PositiveIntegerField(
        default=0,
    )
    errors_count = models.PositiveIntegerField(
        default=0,
    )

    reviewer_notes = models.TextField(
        blank=True,
    )

    assigned_approver = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_vat_returns",
    )
    submitted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_vat_returns",
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_vat_returns",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    filing_reference = models.CharField(
        max_length=120,
        blank=True,
    )
    submission_date = models.DateField(
        null=True,
        blank=True,
    )
    filed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="filed_vat_returns",
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS,
        default="NOT_PAID",
    )
    payment_reference = models.CharField(
        max_length=120,
        blank=True,
    )
    payment_account = models.CharField(
        max_length=180,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS,
        default="DRAFT",
    )

    class Meta:
        ordering = [
            "-period_to",
            "-id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "branch_scope",
                    "return_type",
                    "period_from",
                    "period_to",
                ],
                name="uniq_vat_return_scope_period",
            )
        ]

    def __str__(self):
        return f"{self.return_type} " f"{self.period_from} - {self.period_to}"


class VatReturnBox(TimeStampedModel):
    vat_return = models.ForeignKey(
        VatReturn,
        related_name="boxes",
        on_delete=models.CASCADE,
    )
    box_number = models.CharField(
        max_length=20,
    )
    description = models.CharField(
        max_length=255,
    )
    taxable_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    vat_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    adjustment_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    final_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )
    status = models.CharField(
        max_length=20,
        default="VALID",
    )

    class Meta:
        ordering = [
            "box_number",
            "id",
        ]


class Budget(TimeStampedModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("ACTIVE", "Active"),
        ("REJECTED", "Rejected"),
        ("ARCHIVED", "Archived"),
    ]

    budget_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    budget_name = models.CharField(max_length=180, blank=True, null=True)
    budget_type = models.CharField(max_length=40, blank=True, null=True)
    fiscal_year = models.CharField(max_length=20, blank=True, null=True)

    company_name = models.CharField(max_length=180, default="Ghaza Computer TR LLC")
    branch_scope = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finance_budgets",
    )
    department_scope = models.CharField(max_length=150, blank=True)
    currency = models.CharField(max_length=3, default="AED")

    start_date = models.DateField()
    end_date = models.DateField()

    budget_owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="owned_budgets",
        blank=True,
        null=True,
    )
    description = models.TextField(blank=True, null=True)

    revenue_growth_percent = models.DecimalField(
        max_digits=7, decimal_places=2, default=0
    )
    cost_inflation_percent = models.DecimalField(
        max_digits=7, decimal_places=2, default=0
    )
    headcount_growth_percent = models.DecimalField(
        max_digits=7, decimal_places=2, default=0
    )
    exchange_rate_assumption = models.DecimalField(
        max_digits=18, decimal_places=6, default=1
    )

    control_level = models.CharField(max_length=50, default="ACCOUNT_DEPARTMENT_BRANCH")
    warning_threshold_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=80
    )
    block_threshold_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=100
    )
    commitment_basis = models.CharField(max_length=50, default="ACTUAL_PO_REQUISITION")
    variance_tolerance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    revision_policy = models.CharField(max_length=40, default="APPROVAL_REQUIRED")

    enable_budget_control = models.BooleanField(default=True)
    block_over_budget = models.BooleanField(default=True)
    include_commitments = models.BooleanField(default=True)
    allow_budget_transfers = models.BooleanField(default=True)

    approval_workflow = models.CharField(max_length=80, default="DEPT_FINANCE_MD")
    primary_approver = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="budget_primary_approvals",
    )
    approval_priority = models.CharField(max_length=20, default="NORMAL")
    approval_notes = models.TextField(blank=True)

    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=30, choices=STATUS, default="DRAFT")

    submitted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_budgets",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_budgets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_budgets",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    activated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activated_budgets",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    @property
    def total_budget(self):
        return sum((line.annual_total for line in self.lines.all()), Decimal("0"))


class BudgetLine(TimeStampedModel):
    budget = models.ForeignKey(Budget, related_name="lines", on_delete=models.CASCADE)
    account = models.ForeignKey("finance.ChartOfAccount", on_delete=models.PROTECT)
    department = models.CharField(max_length=150, blank=True)
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.PROTECT
    )
    cost_center = models.CharField(max_length=150, blank=True)

    jan = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    feb = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    mar = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    apr = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    may = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    jun = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    jul = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    aug = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    sep = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    oct = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    nov = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    dec = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    @property
    def annual_total(self):
        return sum(
            (
                self.jan,
                self.feb,
                self.mar,
                self.apr,
                self.may,
                self.jun,
                self.jul,
                self.aug,
                self.sep,
                self.oct,
                self.nov,
                self.dec,
            ),
            Decimal("0"),
        )


class BudgetRevision(TimeStampedModel):
    STATUS = [
        ("DRAFT", "Draft"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    revision_number = models.CharField(max_length=50, unique=True)
    budget = models.ForeignKey(
        Budget, related_name="revisions", on_delete=models.PROTECT
    )
    revision_date = models.DateField(default=timezone.localdate)
    revision_type = models.CharField(max_length=40)
    from_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    to_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS, default="DRAFT")
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_budget_revisions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)


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
        ("OPEN", "Open"),
        ("SENT", "Sent"),  # legacy compatibility
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
        max_length=30, choices=CREDIT_TERMS, default="NET_30"
    )
    customer_credit_limit = models.DecimalField(
        max_digits=16, decimal_places=2, default=0
    )
    linked_sales_invoice_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS, default="DRAFT")

    customer_po_reference = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=3, default="AED")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    salesperson_name = models.CharField(max_length=150, blank=True)
    price_list_name = models.CharField(max_length=150, blank=True)
    place_of_supply = models.CharField(max_length=100, blank=True)
    revenue_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="receivable_revenue_invoices",
    )
    cost_center = models.CharField(max_length=100, blank=True)
    billing_address = models.TextField(blank=True)
    delivery_address = models.TextField(blank=True)
    invoice_narration = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    automatic_overdue_reminders = models.BooleanField(default=True)
    first_reminder_days_before = models.PositiveSmallIntegerField(default=7)
    repeat_reminder_days = models.PositiveSmallIntegerField(default=7)
    allow_credit_note_write_off = models.BooleanField(
        default=False
    )  # legacy DB field only
    auto_post_to_ledger = models.BooleanField(default=True)
    credit_override_approved = models.BooleanField(default=False)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_receivable_invoices",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_receivable_invoices",
    )
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True)
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
    TAX_CATEGORIES = [
        ("STANDARD", "VAT 5%"),
        ("ZERO_RATED", "Zero Rated"),
        ("EXEMPT", "Exempt"),
        ("NON_VAT", "Non-VAT"),
    ]
    invoice = models.ForeignKey(
        ReceivableInvoice, related_name="lines", on_delete=models.CASCADE
    )
    item_service = models.CharField(max_length=180, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    tax_category = models.CharField(
        max_length=30, choices=TAX_CATEGORIES, default="STANDARD"
    )
    vat_rate = models.DecimalField(max_digits=6, decimal_places=3, default=5)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class ReceivableInvoiceAttachment(TimeStampedModel):
    invoice = models.ForeignKey(
        ReceivableInvoice, related_name="attachments", on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="finance/receivables/supporting/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receivable_invoice_attachments",
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
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="finance_receipts"
    )
    receipt_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(
        max_length=30, choices=METHODS, default="BANK_TRANSFER"
    )
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-receipt_date", "-id"]

    @property
    def allocated_amount(self):
        return self.amount if self.invoice_id else Decimal("0")

    @property
    def unallocated_amount(self):
        return max(
            Decimal("0"),
            Decimal(self.amount or 0) - Decimal(self.allocated_amount or 0),
        )


class BankTransaction(TimeStampedModel, BranchAwareModel):
    TRANSACTION_TYPES = [
        ("RECEIPT", "Receipt"),
        ("PAYMENT", "Payment"),
        ("TRANSFER", "Transfer"),
        ("BANK_CHARGE", "Bank Charge"),
        ("ADJUSTMENT", "Adjustment"),
    ]

    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    voucher_number = models.CharField(
        max_length=50,
        unique=True,
    )

    transaction_date = models.DateField()

    transaction_type = models.CharField(
        max_length=30,
        choices=TRANSACTION_TYPES,
    )

    particulars = models.CharField(
        max_length=255,
    )

    receipt_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )

    payment_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )

    running_balance = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
    )

    reference = models.CharField(
        max_length=120,
        blank=True,
    )

    is_bank_statement = models.BooleanField(
        default=False,
    )

    is_book_entry = models.BooleanField(
        default=True,
    )

    reconciliation_status = models.CharField(
        max_length=30,
        default="UNMATCHED",
    )

    reconciled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reconciled_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reconciled_bank_transactions",
    )

    class Meta:
        ordering = [
            "transaction_date",
            "id",
        ]


class BankFundTransfer(TimeStampedModel, BranchAwareModel):
    reference_number = models.CharField(
        max_length=50,
        unique=True,
    )

    from_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
    )

    to_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
    )

    transfer_date = models.DateField()

    amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
    )

    notes = models.TextField(
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        default="POSTED",
    )

    journal = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
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
        ("POSTED", "Posted"),
        ("REJECTED", "Rejected"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
        ("OVERDUE", "Overdue"),
        ("CANCELLED", "Cancelled"),
    ]
    TERMS = [
        ("DUE_ON_RECEIPT", "Due on Receipt"),
        ("NET_15", "Net 15"),
        ("NET_30", "Net 30"),
        ("NET_60", "Net 60"),
    ]
    MATCH_METHODS = [
        ("THREE_WAY", "Three-way match"),
        ("TWO_WAY", "Two-way match"),
        ("NO_PO", "No PO"),
    ]
    MATCH_STATUS = [
        ("NOT_MATCHED", "Not Matched"),
        ("MATCHED", "Matched"),
        ("VARIANCE", "Variance"),
    ]
    PRIORITIES = [
        ("NORMAL", "Normal"),
        ("HIGH", "High"),
        ("URGENT", "Urgent"),
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

    currency = models.CharField(max_length=3, default="AED")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    payment_method = models.CharField(max_length=30, blank=True)
    buyer_requester = models.CharField(max_length=150, blank=True)

    purchase_order_id = models.PositiveBigIntegerField(null=True, blank=True)
    grn_id = models.PositiveBigIntegerField(null=True, blank=True)
    match_method = models.CharField(
        max_length=30, choices=MATCH_METHODS, default="NO_PO"
    )
    match_status = models.CharField(
        max_length=30, choices=MATCH_STATUS, default="NOT_MATCHED"
    )

    expense_account = models.ForeignKey(
        "finance.ChartOfAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payable_expense_bills",
    )
    cost_center = models.CharField(max_length=100, blank=True)
    project = models.CharField(max_length=100, blank=True)

    subtotal = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
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
    bill_narration = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    approval_workflow = models.CharField(
        max_length=100,
        default="AP_ACCOUNTANT_FINANCE_MANAGER",
        blank=True,
    )
    approval_priority = models.CharField(
        max_length=20, choices=PRIORITIES, default="NORMAL"
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

    rejected_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_payable_bills",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    matched_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="matched_payable_bills",
    )
    matched_at = models.DateTimeField(null=True, blank=True)

    posted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_payable_bills",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

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
    TAX_CATEGORIES = [
        ("STANDARD", "VAT 5%"),
        ("ZERO_RATED", "Zero Rated"),
        ("EXEMPT", "Exempt"),
        ("NON_VAT", "Non-VAT"),
    ]

    bill = models.ForeignKey(
        PayableBill, related_name="lines", on_delete=models.CASCADE
    )
    item_expense = models.CharField(max_length=180, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    tax_category = models.CharField(
        max_length=30, choices=TAX_CATEGORIES, default="STANDARD"
    )
    vat_rate = models.DecimalField(max_digits=6, decimal_places=3, default=5)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class PayableBillAttachment(TimeStampedModel):
    bill = models.ForeignKey(
        PayableBill, related_name="attachments", on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="finance/payables/supporting/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payable_bill_attachments",
    )


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
