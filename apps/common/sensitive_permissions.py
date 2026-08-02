from apps.common.permission_helpers import (
    has_erp_permission,
    is_admin_user,
)

SENSITIVE_OPERATION_CODES = {
    "view_restricted_stock": ("inventory.restricted_stock.view"),
    "manage_restricted_stock": ("inventory.restricted_stock.manage"),
    "create_restricted_purchase": ("inventory.restricted_stock.purchase"),
    "view_restricted_purchase": ("inventory.restricted_stock.view"),
    "create_non_standard_tax_sale": ("sales.non_vat.use"),
    "view_non_standard_tax_sale": ("sales.non_vat.view"),
    "manage_non_standard_tax_sale": ("sales.non_vat.manage"),
    "create_non_standard_tax_purchase": ("purchases.non_vat.use"),
    "view_non_standard_tax_purchase": ("purchases.non_vat.view"),
    "manage_non_standard_tax_purchase": ("purchases.non_vat.manage"),
    "view_full_stock": ("inventory.stock.view"),
    "view_tax_sensitive_reports": ("finance.tax.view"),
    "view_complete_records": ("audit_logs.audit_logs.view"),
}


def has_sensitive_permission(
    user,
    code,
):
    if not user or not getattr(
        user,
        "is_authenticated",
        False,
    ):
        return False

    if is_admin_user(user):
        return True

    permission_code = SENSITIVE_OPERATION_CODES.get(
        code,
        code,
    )

    if has_erp_permission(
        user,
        permission_code,
    ):
        return True

    # Backward-compatible support for legacy operation codes.
    checker = getattr(
        user,
        "has_operation_permission",
        None,
    )

    return bool(checker and checker(permission_code))


def can_view_restricted(user):
    return any(
        has_sensitive_permission(
            user,
            code,
        )
        for code in (
            "view_restricted_stock",
            "view_full_stock",
            "view_complete_records",
        )
    )


def can_use_non_vat_sale(user):
    return has_sensitive_permission(
        user,
        "create_non_standard_tax_sale",
    )


def can_view_non_vat_sale(user):
    return has_sensitive_permission(
        user,
        "view_non_standard_tax_sale",
    )
