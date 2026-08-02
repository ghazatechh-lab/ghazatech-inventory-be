import re

METHOD_ACTION = {
    "GET": "view",
    "HEAD": "view",
    "OPTIONS": "view",
    "POST": "create",
    "PUT": "edit",
    "PATCH": "edit",
    "DELETE": "delete",
}


ACTION_ALIASES = {
    "approve": "approve",
    "reject": "reject",
    "confirm": "confirm",
    "cancel": "cancel",
    "void": "void",
    "issue": "issue",
    "dispatch": "dispatch",
    "receive": "receive",
    "deliver": "deliver",
    "clear": "clear",
    "reverse": "reverse",
    "convert": "convert",
    "export": "export",
    "generate": "generate",
    "mark-paid": "mark_paid",
    "mark_paid": "mark_paid",
    "post": "post",
    "close": "close",
    "reopen": "reopen",
    "reconcile": "reconcile",
    "refund": "refund",
    "file": "file",
}


ROUTE_RESOURCE_RULES = [
    (r"^/api/branches", "branches.branches"),
    (r"^/api/categories", "inventory.categories"),
    (r"^/api/brands", "inventory.brands"),
    (r"^/api/racks", "inventory.racks"),
    (r"^/api/products", "inventory.products"),
    (r"^/api/inventory/stock-adjustments", "inventory.adjustments"),
    (r"^/api/inventory/stock-movements", "inventory.movements"),
    (r"^/api/inventory/low-stock", "inventory.low_stock"),
    (r"^/api/inventory/stock", "inventory.stock"),
    (r"^/api/transfers", "inventory.transfers"),
    (r"^/api/customers", "customers.customers"),
    (r"^/api/suppliers", "suppliers.suppliers"),
    (r"^/api/sales/quotations", "sales.quotations"),
    (r"^/api/sales/orders", "sales.orders"),
    (r"^/api/sales/delivery-notes", "sales.delivery_notes"),
    (r"^/api/sales/invoices", "sales.invoices"),
    (r"^/api/sales/pos", "sales.pos"),
    (r"^/api/sales/payments", "sales.payments"),
    (r"^/api/sales/credit-notes", "sales.credit_notes"),
    (r"^/api/sales/returns", "sales.returns"),
    (r"^/api/sales/price-lists", "sales.price_lists"),
    (r"^/api/purchases/orders", "purchases.orders"),
    (r"^/api/purchases/shipments", "purchases.shipments"),
    (r"^/api/purchases/grn", "purchases.grn"),
    (r"^/api/purchases/bills", "purchases.bills"),
    (r"^/api/purchases/supplier-payments", "purchases.payments"),
    (r"^/api/purchases/supplier-returns", "purchases.returns"),
    (r"^/api/purchases/vendor-credits", "purchases.vendor_credits"),
    (r"^/api/purchases/expenses", "purchases.expenses"),
    (r"^/api/hrms/employees", "hrms.employees"),
    (r"^/api/hrms/attendance", "hrms.attendance"),
    (r"^/api/hrms/leaves", "hrms.leaves"),
    (r"^/api/hrms/payroll", "hrms.payroll"),
    (r"^/api/hrms/salary", "hrms.salary_history"),
    (r"^/api/hrms/document", "hrms.documents"),
    (r"^/api/finance/chart-of-accounts", "finance.chart_of_accounts"),
    (r"^/api/finance/journal", "finance.journal_entries"),
    (r"^/api/finance/general-ledger", "finance.general_ledger"),
    (r"^/api/finance/receivables", "finance.receivables"),
    (r"^/api/finance/payables", "finance.payables"),
    (r"^/api/finance/bank", "finance.bank_cash"),
    (r"^/api/finance/fixed-assets", "finance.fixed_assets"),
    (r"^/api/finance/tax", "finance.tax"),
    (r"^/api/finance/budget", "finance.budgeting"),
    (r"^/api/finance/reports", "finance.financial_reports"),
    (r"^/api/finance/period-close", "finance.period_close"),
    (r"^/api/finance/consolidation", "finance.branch_consolidation"),
    (r"^/api/reports/dashboard", "reports.dashboard"),
    (r"^/api/reports/sales", "reports.sales"),
    (r"^/api/reports/purchases", "reports.purchases"),
    (r"^/api/reports/inventory", "reports.inventory"),
    (r"^/api/reports/hrms", "reports.hrms"),
    (r"^/api/reports/finance", "reports.finance"),
    (r"^/api/notifications", "notifications.notifications"),
    (r"^/api/audit-logs", "audit_logs.audit_logs"),
    (r"^/api/accounts/users", "accounts.users"),
    (r"^/api/accounts/roles", "accounts.roles"),
    (r"^/api/settings", "accounts.settings"),
]


SPECIAL_PERMISSION_RULES = [
    (
        re.compile(r"^/api/(sales|purchases)/.+/(vat|tax)(/|$)"),
        {
            "GET": "{module}.vat.view",
            "POST": "{module}.vat.manage",
            "PUT": "{module}.vat.manage",
            "PATCH": "{module}.vat.manage",
            "DELETE": "{module}.vat.manage",
        },
    ),
]


def resolve_permission_code(request):
    path = request.path.rstrip("/") or "/"
    method = request.method.upper()

    for pattern, method_map in SPECIAL_PERMISSION_RULES:
        match = pattern.search(path)

        if match:
            template = method_map.get(method)

            if template:
                return template.format(module=match.group(1))

    resource_prefix = None

    for pattern, prefix in ROUTE_RESOURCE_RULES:
        if re.search(pattern, path):
            resource_prefix = prefix
            break

    if not resource_prefix:
        return None

    last_segment = path.rsplit("/", 1)[-1]
    action = ACTION_ALIASES.get(last_segment)

    if not action:
        action = METHOD_ACTION.get(method)

    if not action:
        return None

    return f"{resource_prefix}.{action}"
