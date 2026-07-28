from rest_framework.permissions import BasePermission

SAFE_PUBLIC_PREFIXES = (
    "/api/auth/login/",
    "/api/auth/refresh/",
    "/api/auth/logout/",
    "/api/auth/me/",
    "/api/auth/profile/",
    "/api/auth/change-password/",
    "/api/schema/",
    "/api/docs/",
)

PATH_RESOURCE_MAP = [
    ("/api/auth/users", "settings.users"),
    ("/api/auth/roles", "settings.roles"),
    ("/api/branches", "settings.branches"),
    ("/api/categories", "inventory.categories"),
    ("/api/brands", "inventory.brands"),
    ("/api/racks", "inventory.racks"),
    ("/api/products", "inventory.products"),
    ("/api/inventory/stock", "inventory.stock"),
    ("/api/inventory/movements", "inventory.movements"),
    ("/api/inventory/adjustments", "inventory.adjustments"),
    ("/api/transfers", "inventory.transfers"),
    ("/api/suppliers", "purchase.suppliers"),
    ("/api/purchases/orders", "purchase.purchase_orders"),
    ("/api/purchases/grn", "purchase.grn"),
    ("/api/purchases/supplier-bills", "purchase.supplier_bills"),
    ("/api/purchases/supplier-payments", "purchase.supplier_payments"),
    ("/api/purchases/supplier-returns", "purchase.supplier_returns"),
    ("/api/purchases/vendor-credits", "purchase.vendor_credits"),
    ("/api/shipments", "purchase.shipments"),
    ("/api/customers", "sales.customers"),
    ("/api/sales/quotations", "sales.quotations"),
    ("/api/sales/invoices", "sales.invoices"),
    ("/api/sales/pos", "sales.pos"),
    ("/api/sales/payments", "sales.sales_payments"),
    ("/api/sales/credit-notes", "sales.credit_notes"),
    ("/api/finance/expenses", "accounting.expenses"),
    ("/api/finance/receivables", "accounting.receivables"),
    ("/api/finance/payables", "accounting.payables"),
    ("/api/finance/cash-register", "accounting.cash_register"),
    ("/api/finance/bank-accounts", "accounting.bank_accounts"),
    ("/api/finance/ledger", "accounting.ledger"),
    ("/api/hrms/employees", "hrms.employees"),
    ("/api/hrms/attendance", "hrms.attendance"),
    ("/api/hrms/leaves", "hrms.leaves"),
    ("/api/hrms/payroll", "hrms.payroll"),
    ("/api/hrms/document-expiry", "hrms.document_expiry"),
    ("/api/reports", "reports.reports"),
    ("/api/dashboard", "dashboard.dashboard"),
    ("/api/audit-logs", "settings.audit_logs"),
]

ACTION_WORDS = {
    "approve": "approve",
    "approved": "approve",
    "reject": "reject",
    "cancel": "cancel",
    "convert": "convert",
    "export": "export",
    "print": "print",
    "process": "process",
    "close": "close",
    "activate": "activate",
    "deactivate": "activate",
}


def action_from_request(request, view):
    action = str(getattr(view, "action", "") or "").lower()
    for word, permission_action in ACTION_WORDS.items():
        if word in action or word in request.path.lower():
            return permission_action
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return "view"
    if request.method == "POST":
        return "create"
    if request.method in ("PUT", "PATCH"):
        return "edit"
    if request.method == "DELETE":
        return "delete"
    return "view"


def resource_from_path(path):
    for prefix, resource in PATH_RESOURCE_MAP:
        if path.startswith(prefix):
            return resource
    return None


class RoleOperationPermission(BasePermission):
    message = "Your role does not have permission to perform this operation."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if any(request.path.startswith(prefix) for prefix in SAFE_PUBLIC_PREFIXES):
            return True
        if user.is_superuser or (user.role and user.role.code == "ADMIN"):
            return True
        resource = resource_from_path(request.path)
        if not resource:
            return True
        permission_code = f"{resource}.{action_from_request(request, view)}"
        return user.has_operation_permission(permission_code)


class IsBranchUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
