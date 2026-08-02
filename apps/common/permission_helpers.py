from functools import lru_cache

ADMIN_ROLE_CODES = {
    "ADMIN",
    "SUPER_ADMIN",
}


def get_role_code(user):
    role = getattr(user, "role", None)

    return (
        str(
            getattr(role, "code", None)
            or getattr(user, "role_code", None)
            or getattr(user, "role_name", None)
            or ""
        )
        .strip()
        .upper()
    )


def is_admin_user(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (
            getattr(user, "is_superuser", False)
            or get_role_code(user) in ADMIN_ROLE_CODES
        )
    )


def _permission_strings_from_iterable(values):
    result = set()

    for value in values or []:
        if isinstance(value, str):
            code = value
        else:
            code = (
                getattr(value, "code", None)
                or getattr(value, "permission_code", None)
                or getattr(value, "codename", None)
                or str(value)
            )

        if code:
            result.add(str(code).strip())

    return result


def collect_user_permissions(user):
    if not user or not getattr(user, "is_authenticated", False):
        return set()

    if is_admin_user(user):
        return {"*"}

    permissions = set()

    for attribute in (
        "permissions",
        "permission_codes",
        "all_permissions",
        "effective_permissions",
    ):
        value = getattr(user, attribute, None)

        if callable(value):
            try:
                value = value()
            except TypeError:
                continue

        if hasattr(value, "all"):
            value = value.all()

        permissions.update(_permission_strings_from_iterable(value))

    role = getattr(user, "role", None)

    if role:
        for attribute in (
            "permissions",
            "permission_codes",
        ):
            value = getattr(role, attribute, None)

            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue

            if hasattr(value, "all"):
                value = value.all()

            permissions.update(_permission_strings_from_iterable(value))

    if hasattr(user, "get_all_permissions"):
        try:
            permissions.update(user.get_all_permissions())
        except Exception:
            pass

    return permissions


def has_erp_permission(user, permission_code):
    if not permission_code:
        return True

    if is_admin_user(user):
        return True

    permissions = collect_user_permissions(user)

    if "*" in permissions or permission_code in permissions:
        return True

    # Support resource or module wildcards.
    parts = permission_code.split(".")

    if len(parts) >= 2:
        if f"{parts[0]}.*" in permissions:
            return True

        if f"{parts[0]}.{parts[1]}.*" in permissions:
            return True

    return False


def has_any_erp_permission(user, permission_codes):
    return any(has_erp_permission(user, code) for code in permission_codes or [])


def has_all_erp_permissions(user, permission_codes):
    return all(has_erp_permission(user, code) for code in permission_codes or [])
