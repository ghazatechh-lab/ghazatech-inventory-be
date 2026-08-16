PERMISSION_GROUPS = [
    {
        "module": "dashboard",
        "label": "Dashboard",
        "resources": [
            {
                "resource": "dashboard",
                "label": "Dashboard",
                "actions": ["view"],
            },
        ],
    },
    # ------------------------------------------------------------------
    # BRANCH ACCESS
    # ------------------------------------------------------------------
    # These permissions are intentionally two-part:
    #   branches.switch
    #   branches.view_all
    #
    # `code_prefix` is handled by all_permission_codes() below.
    {
        "module": "branches",
        "label": "Branch Access",
        "resources": [
            {
                "resource": "active_branch",
                "label": "Active Branch",
                "code_prefix": "branches",
                "actions": ["switch", "view_all"],
                "action_labels": {
                    "switch": "Change Active Branch",
                    "view_all": "View All Branches",
                },
                "action_descriptions": {
                    "switch": (
                        "Allow the user to change the active working branch "
                        "from the application header."
                    ),
                    "view_all": (
                        "Allow the user to select All Branches and view "
                        "combined branch-scoped records."
                    ),
                },
            },
        ],
    },
    # ------------------------------------------------------------------
    # INVENTORY
    # ------------------------------------------------------------------
    {
        "module": "inventory",
        "label": "Inventory",
        "resources": [
            {
                "resource": "categories",
                "label": "Categories",
                "actions": ["view", "create", "edit", "delete"],
            },
            {
                "resource": "racks",
                "label": "Racks",
                "actions": ["view", "create", "edit", "delete"],
            },
            {
                "resource": "products",
                "label": "Products",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "import",
                    "export",
                ],
            },
            {
                "resource": "stock",
                "label": "Stock Overview",
                "actions": ["view", "export"],
            },
            {
                "resource": "movements",
                "label": "Stock Movements",
                "actions": ["view", "export"],
            },
            {
                "resource": "adjustments",
                "label": "Stock Adjustments",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                ],
            },
            {
                "resource": "transfers",
                "label": "Stock Transfers",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "dispatch",
                    "receive",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "low_stock",
                "label": "Low Stock",
                "actions": ["view", "export"],
            },
        ],
    },
    # ------------------------------------------------------------------
    # PURCHASES
    # ------------------------------------------------------------------
    {
        "module": "purchase",
        "label": "Purchase",
        "resources": [
            {
                "resource": "suppliers",
                "label": "Suppliers",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "purchase_orders",
                "label": "Purchase Orders",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "shipments",
                "label": "Purchase Shipments",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "confirm",
                    "receive",
                    "qc",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "grn",
                "label": "Goods Received Notes",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "confirm",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "supplier_bills",
                "label": "Supplier Bills",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "supplier_payments",
                "label": "Supplier Payments",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "supplier_returns",
                "label": "Supplier Returns",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "vendor_credits",
                "label": "Vendor Credits",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "expenses",
                "label": "Purchase Expenses",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "print",
                    "export",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------
    # SALES
    # ------------------------------------------------------------------
    {
        "module": "sales",
        "label": "Sales",
        "resources": [
            {
                "resource": "customers",
                "label": "Customers",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "quotations",
                "label": "Quotations",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "convert",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "sales_orders",
                "label": "Sales Orders",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "convert",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "delivery_notes",
                "label": "Delivery Notes",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "deliver",
                    "cancel",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "invoices",
                "label": "Invoices",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "record_payment",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "pos",
                "label": "Direct Sale / POS",
                "actions": [
                    "view",
                    "create",
                    "print",
                ],
            },
            {
                "resource": "service",
                "label": "Service & Repair",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "assign",
                    "complete",
                    "create_invoice",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "sales_payments",
                "label": "Sales Payments",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "sales_returns",
                "label": "Sales Returns",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "credit_notes",
                "label": "Credit Notes",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "cancel",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "price_lists",
                "label": "Price Lists & Discounts",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "selling",
                "label": "Selling Controls",
                "actions": [
                    "discount",
                    "price_override",
                ],
                "action_labels": {
                    "discount": "Apply Sales Discount",
                    "price_override": "Override Selling Price",
                },
            },
        ],
    },
    # ------------------------------------------------------------------
    # ACCOUNTING
    # ------------------------------------------------------------------
    {
        "module": "accounting",
        "label": "Accounting",
        "resources": [
            {
                "resource": "dashboard",
                "label": "Dashboard",
                "actions": ["view"],
            },
            {
                "resource": "chart_of_accounts",
                "label": "Chart of Accounts",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "journal_entries",
                "label": "Journal Entries",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "post",
                    "reverse",
                    "export",
                    "print",
                ],
            },
            {
                "resource": "general_ledger",
                "label": "General Ledger",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "receivables",
                "label": "Accounts Receivable",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "payables",
                "label": "Accounts Payable",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "bank_cash",
                "label": "Bank & Cash",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "cash_registers",
                "label": "Cash Registers",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "close",
                    "export",
                ],
            },
            {
                "resource": "fixed_assets",
                "label": "Fixed Assets",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "tax",
                "label": "VAT / Tax",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "budgeting",
                "label": "Budgeting",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "export",
                ],
            },
            {
                "resource": "period_close",
                "label": "Period Close",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "close",
                ],
            },
            {
                "resource": "branch_consolidation",
                "label": "Branch Consolidation",
                "actions": [
                    "view",
                    "export",
                    "print",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------
    # HRMS
    # ------------------------------------------------------------------
    {
        "module": "hrms",
        "label": "HRMS",
        "resources": [
            {
                "resource": "employees",
                "label": "Employees",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "departments",
                "label": "Departments",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                ],
            },
            {
                "resource": "designations",
                "label": "Designations",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                ],
            },
            {
                "resource": "attendance",
                "label": "Attendance",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "export",
                ],
            },
            {
                "resource": "leaves",
                "label": "Leave Requests",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "approve",
                    "reject",
                    "export",
                ],
            },
            {
                "resource": "payroll",
                "label": "Payroll",
                "actions": [
                    "view",
                    "create",
                    "approve",
                    "process",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "salary_history",
                "label": "Salary History",
                "actions": [
                    "view",
                    "create",
                    "edit",
                ],
            },
            {
                "resource": "certificates_letters",
                "label": "Certificates & Letters",
                "actions": [
                    "view",
                    "create",
                    "print",
                    "export",
                ],
            },
            {
                "resource": "document_expiry",
                "label": "Document Expiry",
                "actions": [
                    "view",
                    "export",
                ],
            },
        ],
    },
    # ------------------------------------------------------------------
    # REPORTS
    # ------------------------------------------------------------------
    # Financial Reports intentionally live here, not under Accounting.
    {
        "module": "reports",
        "label": "Reports",
        "resources": [
            {
                "resource": "dashboard",
                "label": "Reports Dashboard",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "sales",
                "label": "Sales Reports",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "purchase",
                "label": "Purchase Reports",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "inventory",
                "label": "Inventory Reports",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "hrms",
                "label": "HRMS Reports",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "finance",
                "label": "Finance Reports",
                "actions": ["view", "export", "print"],
            },
        ],
    },
    # ------------------------------------------------------------------
    # SETTINGS & SECURITY
    # ------------------------------------------------------------------
    {
        "module": "settings",
        "label": "Settings & Security",
        "resources": [
            {
                "resource": "branches",
                "label": "Branches",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                ],
            },
            {
                "resource": "users",
                "label": "Users",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                    "activate",
                ],
            },
            {
                "resource": "roles",
                "label": "Roles & Permissions",
                "actions": [
                    "view",
                    "create",
                    "edit",
                    "delete",
                ],
            },
            {
                "resource": "audit_logs",
                "label": "Audit Logs",
                "actions": [
                    "view",
                    "export",
                ],
            },
            {
                "resource": "settings",
                "label": "System Settings",
                "actions": [
                    "view",
                    "edit",
                ],
            },
        ],
    },
]


def permission_code(group, resource, action):
    """
    Return the canonical permission code.

    Most permissions use:
        module.resource.action

    Special permissions such as branch switching can define:
        "code_prefix": "branches"

    which produces:
        branches.switch
        branches.view_all
    """
    code_prefix = resource.get("code_prefix")

    if code_prefix:
        return f"{code_prefix}.{action}"

    return f"{group['module']}." f"{resource['resource']}." f"{action}"


def all_permission_codes():
    return [
        permission_code(group, resource, action)
        for group in PERMISSION_GROUPS
        for resource in group["resources"]
        for action in resource["actions"]
    ]


def permission_catalog():
    """
    Return a flattened permission catalog.

    This is useful for serializers, permission-sync commands, role forms,
    and API responses that need both the permission code and human labels.
    """
    rows = []

    for group in PERMISSION_GROUPS:
        for resource in group["resources"]:
            action_labels = resource.get("action_labels", {})
            action_descriptions = resource.get(
                "action_descriptions",
                {},
            )

            for action in resource["actions"]:
                rows.append(
                    {
                        "code": permission_code(
                            group,
                            resource,
                            action,
                        ),
                        "module": group["module"],
                        "module_label": group["label"],
                        "resource": resource["resource"],
                        "resource_label": resource["label"],
                        "action": action,
                        "action_label": action_labels.get(
                            action,
                            action.replace("_", " ").title(),
                        ),
                        "description": action_descriptions.get(
                            action,
                            "",
                        ),
                    }
                )

    return rows
