import json

VIEW_ALL_BRANCHES_PERMISSION = "branches.view_all"


def _normalize_permission_codes(value):
    if not value:
        return set()

    if isinstance(value, str):
        stripped = value.strip()

        if not stripped:
            return set()

        try:
            return _normalize_permission_codes(json.loads(stripped))
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return {item.strip() for item in stripped.split(",") if item.strip()}

    if isinstance(value, dict):
        if "permissions" in value:
            return _normalize_permission_codes(value["permissions"])

        return {str(code).strip() for code, enabled in value.items() if enabled is True}

    if isinstance(value, (list, tuple, set)):
        permissions = set()

        for item in value:
            if isinstance(item, str):
                code = item.strip()

                if code:
                    permissions.add(code)

            elif isinstance(item, dict):
                code = (
                    item.get("code")
                    or item.get("permission_code")
                    or item.get("permission")
                    or item.get("name")
                )

                if code:
                    permissions.add(str(code).strip())

        return permissions

    return set()


def get_user_permission_codes(user):
    if not user or not getattr(
        user,
        "is_authenticated",
        False,
    ):
        return set()

    role = getattr(user, "role", None)
    role_code = str(getattr(role, "code", "")).upper()

    if getattr(user, "is_superuser", False) or role_code in {"ADMIN", "SUPER_ADMIN"}:
        return {"*"}

    permissions = set()

    for value in (
        getattr(user, "permissions", None),
        getattr(user, "permission_codes", None),
        getattr(user, "effective_permissions", None),
        getattr(role, "permissions", None),
    ):
        permissions.update(_normalize_permission_codes(value))

    if "branches.branches.view_all" in permissions:
        permissions.add("branches.view_all")

    if "branches.branch_access.view_all" in permissions:
        permissions.add("branches.view_all")

    return permissions


def user_has_permission(user, permission_code):
    permissions = get_user_permission_codes(user)

    if "*" in permissions:
        return True

    if permission_code in permissions:
        return True

    parts = permission_code.split(".")

    wildcard_codes = {
        f"{parts[0]}.*",
    }

    if len(parts) > 1:
        wildcard_codes.add(f"{parts[0]}.{parts[1]}.*")

    return bool(permissions.intersection(wildcard_codes))


def can_view_all_branches(user):
    return user_has_permission(
        user,
        VIEW_ALL_BRANCHES_PERMISSION,
    )


def get_user_branch_id(user):
    if not user:
        return None

    direct_branch_id = getattr(
        user,
        "branch_id",
        None,
    )

    if direct_branch_id:
        return direct_branch_id

    branch = getattr(user, "branch", None)

    if branch:
        return getattr(branch, "id", branch)

    employee = getattr(user, "employee", None)

    if employee:
        return getattr(employee, "branch_id", None)

    return None
