SENSITIVE_OPERATION_CODES = {
    "view_restricted_stock": "inventory.view_restricted_stock",
    "manage_restricted_stock": "inventory.manage_restricted_stock",
    "create_restricted_purchase": "purchases.create_restricted_purchase",
    "view_restricted_purchase": "purchases.view_restricted_purchase",
    "create_non_standard_tax_sale": "sales.create_non_standard_tax_sale",
    "view_non_standard_tax_sale": "sales.view_non_standard_tax_sale",
    "view_full_stock": "reports.view_full_stock",
    "view_tax_sensitive_reports": "reports.view_tax_sensitive_reports",
    "view_complete_records": "audit.view_complete_records",
}


def has_sensitive_permission(user, code):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if (
        user.is_superuser
        or getattr(
            getattr(user, "role", None),
            "code",
            "",
        )
        == "ADMIN"
    ):
        return True

    django_code = code if "." in code else f"inventory.{code}"

    if user.has_perm(django_code):
        return True

    operation = SENSITIVE_OPERATION_CODES.get(
        code,
        code,
    )

    checker = getattr(
        user,
        "has_operation_permission",
        None,
    )

    return bool(checker and checker(operation))


def can_view_restricted(user):
    return any(
        has_sensitive_permission(user, code)
        for code in (
            "view_restricted_stock",
            "view_full_stock",
            "view_complete_records",
        )
    )
