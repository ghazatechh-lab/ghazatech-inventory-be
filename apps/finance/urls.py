from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountingDashboardViewSet,
    AccountingPeriodViewSet,
    BankAccountViewSet,
    BudgetViewSet,
    CashRegisterViewSet,
    ChartOfAccountViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    # Fixed Assets
    FixedAssetViewSet,
    FixedAssetDepreciationViewSet,
    FixedAssetTransferViewSet,
    FixedAssetMaintenanceViewSet,
    FixedAssetDisposalViewSet,
    # Existing / legacy asset endpoints
    AssetDepreciationRunViewSet,
    AssetDisposalViewSet,
    # Journals / Ledger
    JournalEntryViewSet,
    LedgerViewSet,
    # Accounts Receivable
    ReceivableInvoiceViewSet,
    ReceivableReceiptViewSet,
    # Accounts Payable
    PayableBillViewSet,
    PayablePaymentViewSet,
    # Bank & Cash
    BankTransactionViewSet,
    BankFundTransferViewSet,
    # VAT / Tax
    TaxRateViewSet,
    VatViewSet,
    VatReturnViewSet,
    VatSettingsViewSet,
    # Reports
    vat_summary,
    trial_balance,
    income_statement,
    balance_sheet,
    cash_flow,
    changes_in_equity,
    branch_consolidation,
    # Period Close
    period_close,
    period_task_toggle,
    period_action,
)

router = DefaultRouter()


# =========================================================
# EXPENSES
# =========================================================

router.register(
    "expenses",
    ExpenseViewSet,
    basename="expense",
)

router.register(
    "expense-categories",
    ExpenseCategoryViewSet,
    basename="expense-category",
)


# =========================================================
# CASH REGISTER
# =========================================================

router.register(
    "cash-register",
    CashRegisterViewSet,
    basename="cash-register",
)


# =========================================================
# BANK & CASH
# =========================================================

router.register(
    "bank-accounts",
    BankAccountViewSet,
    basename="bank-account",
)

router.register(
    "bank-transactions",
    BankTransactionViewSet,
    basename="bank-transaction",
)

router.register(
    "fund-transfers",
    BankFundTransferViewSet,
    basename="fund-transfer",
)


# =========================================================
# CHART OF ACCOUNTS
# =========================================================

router.register(
    "accounts",
    ChartOfAccountViewSet,
    basename="chart-of-account",
)


# =========================================================
# JOURNAL ENTRIES
# =========================================================

router.register(
    "journals",
    JournalEntryViewSet,
    basename="journal-entry",
)


# =========================================================
# LEDGER
# =========================================================

router.register(
    "ledger",
    LedgerViewSet,
    basename="ledger",
)


# =========================================================
# ACCOUNTS RECEIVABLE
# =========================================================

router.register(
    "receivable-invoices",
    ReceivableInvoiceViewSet,
    basename="receivable-invoice",
)

router.register(
    "receivable-receipts",
    ReceivableReceiptViewSet,
    basename="receivable-receipt",
)


# =========================================================
# ACCOUNTS PAYABLE
# =========================================================

router.register(
    "payable-bills",
    PayableBillViewSet,
    basename="payable-bill",
)

router.register(
    "payable-payments",
    PayablePaymentViewSet,
    basename="payable-payment",
)


# =========================================================
# FIXED ASSETS
# =========================================================

router.register(
    "fixed-assets",
    FixedAssetViewSet,
    basename="fixed-asset",
)

router.register(
    "fixed-asset-depreciation",
    FixedAssetDepreciationViewSet,
    basename="fixed-asset-depreciation",
)

router.register(
    "fixed-asset-transfers",
    FixedAssetTransferViewSet,
    basename="fixed-asset-transfer",
)

router.register(
    "fixed-asset-maintenance",
    FixedAssetMaintenanceViewSet,
    basename="fixed-asset-maintenance",
)

router.register(
    "fixed-asset-disposals",
    FixedAssetDisposalViewSet,
    basename="fixed-asset-disposal",
)


# =========================================================
# LEGACY FIXED ASSET ROUTES
# Keep these temporarily if older frontend/backend code
# is still using them.
# =========================================================

router.register(
    "asset-depreciation-runs",
    AssetDepreciationRunViewSet,
    basename="asset-depreciation-run",
)

router.register(
    "asset-disposals",
    AssetDisposalViewSet,
    basename="asset-disposal",
)


# =========================================================
# VAT / TAX
# =========================================================

router.register(
    "tax-rates",
    TaxRateViewSet,
    basename="tax-rate",
)

router.register(
    "vat/returns",
    VatReturnViewSet,
    basename="vat-return",
)

router.register(
    "vat/settings",
    VatSettingsViewSet,
    basename="vat-settings",
)

router.register(
    "vat",
    VatViewSet,
    basename="vat",
)


# =========================================================
# BUDGETS
# =========================================================

router.register(
    "budgets",
    BudgetViewSet,
    basename="budget",
)


# =========================================================
# ACCOUNTING PERIODS
# =========================================================

router.register(
    "periods",
    AccountingPeriodViewSet,
    basename="accounting-period",
)


# =========================================================
# ACCOUNTING DASHBOARD
# =========================================================

router.register(
    "dashboard",
    AccountingDashboardViewSet,
    basename="accounting-dashboard",
)


# =========================================================
# URL PATTERNS
# =========================================================

urlpatterns = router.urls + [
    # -----------------------------------------------------
    # VAT REPORTING
    # -----------------------------------------------------
    path(
        "reporting/vat-summary/",
        vat_summary,
        name="finance-vat-summary",
    ),
    # -----------------------------------------------------
    # FINANCIAL REPORTS
    # -----------------------------------------------------
    path(
        "reporting/reports/trial-balance/",
        trial_balance,
        name="finance-trial-balance",
    ),
    path(
        "reporting/reports/income-statement/",
        income_statement,
        name="finance-income-statement",
    ),
    path(
        "reporting/reports/balance-sheet/",
        balance_sheet,
        name="finance-balance-sheet",
    ),
    path(
        "reporting/reports/cash-flow/",
        cash_flow,
        name="finance-cash-flow",
    ),
    path(
        "reporting/reports/changes-in-equity/",
        changes_in_equity,
        name="finance-changes-equity",
    ),
    path(
        "reporting/branch-consolidation-summary/",
        branch_consolidation,
        name="finance-branch-consolidation",
    ),
    # -----------------------------------------------------
    # PERIOD CLOSE
    # -----------------------------------------------------
    path(
        "reporting/period-close/",
        period_close,
        name="finance-period-close",
    ),
    path(
        "reporting/period-close/<int:period_id>/tasks/<int:task_id>/",
        period_task_toggle,
        name="finance-period-task",
    ),
    path(
        "reporting/period-close/<int:period_id>/<str:action>/",
        period_action,
        name="finance-period-action",
    ),
]
