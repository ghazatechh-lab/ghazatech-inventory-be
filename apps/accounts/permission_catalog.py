PERMISSION_GROUPS = [
    {
        "module": "dashboard",
        "label": "Dashboard",
        "resources": [
            {"resource": "dashboard", "label": "Dashboard", "actions": ["view"]}
        ],
    },
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
                "resource": "brands",
                "label": "Brands",
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
                "actions": ["view", "create", "edit", "delete", "export"],
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
                "actions": ["view", "create", "approve"],
            },
            {
                "resource": "transfers",
                "label": "Stock Transfers",
                "actions": ["view", "create", "edit", "approve", "cancel"],
            },
            {
                "resource": "stock_classification",
                "label": "Stock Classification",
                "actions": ["view", "assign", "change"],
            },
            {
                "resource": "restricted_stock",
                "label": "Restricted Stock",
                "actions": ["view", "manage", "sell", "purchase", "transfer", "adjust"],
            },
        ],
    },
    {
        "module": "purchase",
        "label": "Purchase",
        "resources": [
            {
                "resource": "suppliers",
                "label": "Suppliers",
                "actions": ["view", "create", "edit", "delete", "export"],
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
                "resource": "grn",
                "label": "Goods Received Notes",
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
                "resource": "supplier_bills",
                "label": "Supplier Bills",
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
                "resource": "shipments",
                "label": "Shipments",
                "actions": ["view", "create", "edit", "delete"],
            },
        ],
    },
    {
        "module": "purchases",
        "label": "Purchase Special Access",
        "resources": [
            {
                "resource": "stock_purchase",
                "label": "Stock Purchase Controls",
                "actions": ["regular", "restricted", "vat", "non_vat"],
            },
            {
                "resource": "vat",
                "label": "Purchase VAT",
                "actions": [
                    "view",
                    "manage",
                    "override_rate",
                    "use_zero_rated",
                    "use_exempt",
                    "use_out_of_scope",
                    "use_reverse_charge",
                    "view_reason",
                ],
            },
            {
                "resource": "non_vat",
                "label": "Purchase Non-VAT",
                "actions": ["view", "use", "manage"],
            },
        ],
    },
    {
        "module": "sales",
        "label": "Sales",
        "resources": [
            {
                "resource": "customers",
                "label": "Customers",
                "actions": ["view", "create", "edit", "delete", "export"],
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
                "resource": "invoices",
                "label": "Invoices",
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
                "resource": "pos",
                "label": "Direct Sale / POS",
                "actions": ["view", "create", "print"],
            },
            {
                "resource": "sales_payments",
                "label": "Sales Payments",
                "actions": ["view", "create", "edit", "delete", "print", "export"],
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
                    "print",
                    "export",
                ],
            },
            {
                "resource": "selling",
                "label": "Selling Controls",
                "actions": [
                    "regular",
                    "restricted",
                    "vat",
                    "non_vat",
                    "discount",
                    "price_override",
                ],
            },
            {
                "resource": "vat",
                "label": "Sales VAT",
                "actions": [
                    "view",
                    "manage",
                    "override_rate",
                    "use_zero_rated",
                    "use_exempt",
                    "use_out_of_scope",
                    "use_reverse_charge",
                    "view_reason",
                ],
            },
            {
                "resource": "non_vat",
                "label": "Sales Non-VAT",
                "actions": ["view", "use", "manage"],
            },
        ],
    },
    {
        "module": "accounting",
        "label": "Accounting",
        "resources": [
            {"resource": "dashboard", "label": "Dashboard", "actions": ["view"]},
            {
                "resource": "chart_of_accounts",
                "label": "Chart of Accounts",
                "actions": ["view", "create", "edit", "delete", "export"],
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
                "actions": ["view", "create", "edit", "delete", "export"],
            },
            {
                "resource": "fixed_assets",
                "label": "Fixed Assets",
                "actions": ["view", "create", "edit", "delete", "export"],
            },
            {
                "resource": "tax",
                "label": "VAT / Tax",
                "actions": ["view", "create", "edit", "delete", "export"],
            },
            {
                "resource": "budgeting",
                "label": "Budgeting",
                "actions": ["view", "create", "edit", "delete", "approve", "export"],
            },
            {
                "resource": "financial_reports",
                "label": "Financial Reports",
                "actions": ["view", "export", "print"],
            },
            {
                "resource": "period_close",
                "label": "Period Close",
                "actions": ["view", "create", "edit", "close"],
            },
            {
                "resource": "branch_consolidation",
                "label": "Branch Consolidation",
                "actions": ["view", "export", "print"],
            },
        ],
    },
    {
        "module": "hrms",
        "label": "HRMS",
        "resources": [
            {
                "resource": "employees",
                "label": "Employees",
                "actions": ["view", "create", "edit", "delete", "export"],
            },
            {
                "resource": "attendance",
                "label": "Attendance",
                "actions": ["view", "create", "edit", "delete", "export"],
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
                "actions": ["view", "create", "approve", "process", "print", "export"],
            },
            {
                "resource": "salary_history",
                "label": "Salary Revision",
                "actions": ["view", "create", "edit"],
            },
            {
                "resource": "document_expiry",
                "label": "Document Expiry",
                "actions": ["view", "export"],
            },
        ],
    },
    {
        "module": "reports",
        "label": "Reports",
        "resources": [
            {
                "resource": "reports",
                "label": "All Reports",
                "actions": ["view", "export", "print"],
            }
        ],
    },
    {
        "module": "branches",
        "label": "Branch Controls",
        "description": (
            "Controls branch visibility and whether a user can change "
            "the active branch from the application top bar."
        ),
        "resources": [
            {
                "resource": "branch_access",
                "label": "Branch Access",
                "description": (
                    "Controls whether the user is limited to the assigned "
                    "branch or can view all branch details and records."
                ),
                "code_prefix": "branches",
                "actions": ["view_all"],
                "action_labels": {
                    "view_all": "View All Branches",
                },
                "action_descriptions": {
                    "view_all": (
                        "Allow the user to view all branch details and "
                        "all branch-scoped records."
                    ),
                },
            },
            {
                "resource": "active_branch",
                "label": "Active Branch",
                "description": (
                    "Controls branch switching from the top navigation bar."
                ),
                "code_prefix": "branches",
                "actions": ["switch"],
                "action_labels": {
                    "switch": "Change Active Branch",
                },
                "action_descriptions": {
                    "switch": (
                        "Show the branch selector in the top bar and "
                        "allow changing the active working branch."
                    ),
                },
            },
        ],
    },
    {
        "module": "settings",
        "label": "Settings & Security",
        "resources": [
            {
                "resource": "branches",
                "label": "Branches",
                "actions": ["view", "create", "edit", "delete"],
            },
            {
                "resource": "users",
                "label": "Users",
                "actions": ["view", "create", "edit", "delete", "activate"],
            },
            {
                "resource": "roles",
                "label": "Roles & Permissions",
                "actions": ["view", "create", "edit", "delete"],
            },
            {
                "resource": "audit_logs",
                "label": "Audit Logs",
                "actions": ["view", "export"],
            },
            {
                "resource": "settings",
                "label": "System Settings",
                "actions": ["view", "edit"],
            },
        ],
    },
]


def permission_code(group, resource, action):
    """
    Build a permission code.

    Resources may provide ``code_prefix`` when the permission must use a
    shorter explicit namespace. For example, the top-bar branch permission is
    ``branches.switch`` instead of ``branches.active_branch.switch``.
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
