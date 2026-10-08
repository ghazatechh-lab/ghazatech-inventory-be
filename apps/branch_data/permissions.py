from .routing import VAT, NON_VAT


def _permission_names(source, action):
    prefix = "vat" if source == VAT else "non_vat"
    return (
        f"branch_data.{action}_{prefix}",
        f"{action}_{prefix}",
    )


def user_can_source(user, source, *, write=False, action=None):
    """
    Supports both Django permissions and the existing role/permission systems.

    Superusers always pass. For ordinary users, configure permissions such as:
      branch_data.view_vat
      branch_data.view_non_vat
      branch_data.create_vat_sale
      branch_data.create_non_vat_sale
      branch_data.create_vat_purchase
      branch_data.create_non_vat_purchase
      branch_data.adjust_vat_stock
      branch_data.adjust_non_vat_stock
      branch_data.view_combined_reports
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    action = action or ("change" if write else "view")
    for permission in _permission_names(source, action):
        try:
            if user.has_perm(permission):
                return True
        except Exception:
            pass

    # Compatibility with systems that expose permission codes on the user.
    values = set()
    for attr in ("permission_codes", "permissions", "allowed_permissions"):
        current = getattr(user, attr, None)
        if callable(current):
            try:
                current = current()
            except Exception:
                current = None
        if current:
            if isinstance(current, str):
                values.add(current)
            else:
                try:
                    for item in current:
                        values.add(str(getattr(item, "code", item)))
                except TypeError:
                    pass

    prefix = "vat" if source == VAT else "non_vat"
    candidates = {
        f"{action}_{prefix}",
        f"{action}_{prefix}_data",
        f"access_{prefix}",
    }
    return bool(values.intersection(candidates))
