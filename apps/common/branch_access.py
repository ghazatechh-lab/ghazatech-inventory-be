import json

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q

VIEW_ALL_BRANCHES_PERMISSION = "branches.view_all"
SWITCH_BRANCH_PERMISSION = "branches.switch"


def _normalize_permission_codes(value):
    if not value:
        return set()

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return set()

        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {item.strip() for item in stripped.split(",") if item.strip()}

        return _normalize_permission_codes(parsed)

    if isinstance(value, dict):
        if "permissions" in value:
            return _normalize_permission_codes(value["permissions"])
        if "data" in value:
            return _normalize_permission_codes(value["data"])
        if "results" in value:
            return _normalize_permission_codes(value["results"])

        return {
            str(code).strip()
            for code, enabled in value.items()
            if enabled is True and str(code).strip()
        }

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
                    or item.get("codename")
                    or item.get("name")
                )
                if code:
                    permissions.add(str(code).strip())

        return permissions

    return set()


def get_user_permission_codes(user):
    if not user or not getattr(user, "is_authenticated", False):
        return set()

    role = getattr(user, "role", None)
    role_code = str(getattr(role, "code", "")).strip().upper()

    if getattr(user, "is_superuser", False) or role_code in {
        "ADMIN",
        "SUPER_ADMIN",
        "ADMINISTRATOR",
    }:
        return {"*"}

    permissions = set()

    for value in (
        getattr(user, "permissions", None),
        getattr(user, "permission_codes", None),
        getattr(user, "all_permissions", None),
        getattr(user, "effective_permissions", None),
        getattr(role, "permissions", None),
    ):
        permissions.update(_normalize_permission_codes(value))

    # Compatibility with previous malformed permission codes.
    if "branches.branches.view_all" in permissions:
        permissions.add("branches.view_all")

    if "branches.branch_access.view_all" in permissions:
        permissions.add("branches.view_all")

    return permissions


def user_has_permission(user, permission_code):
    permissions = get_user_permission_codes(user)

    if "*" in permissions or permission_code in permissions:
        return True

    parts = permission_code.split(".")
    wildcard_codes = {f"{parts[0]}.*"}

    if len(parts) > 1:
        wildcard_codes.add(f"{parts[0]}.{parts[1]}.*")

    return bool(permissions.intersection(wildcard_codes))


def can_view_all_branches(user):
    return user_has_permission(user, VIEW_ALL_BRANCHES_PERMISSION)


def can_switch_branches(user):
    return can_view_all_branches(user) or user_has_permission(
        user, SWITCH_BRANCH_PERMISSION
    )


def get_user_branch_id(user):
    if not user:
        return None

    direct_branch_id = getattr(user, "branch_id", None)
    if direct_branch_id:
        return direct_branch_id

    branch = getattr(user, "branch", None)
    if branch:
        return getattr(branch, "id", branch)

    branch_detail = getattr(user, "branch_detail", None)
    if branch_detail:
        return getattr(branch_detail, "id", branch_detail)

    employee = getattr(user, "employee", None)
    if employee:
        employee_branch_id = getattr(employee, "branch_id", None)
        if employee_branch_id:
            return employee_branch_id

        employee_branch = getattr(employee, "branch", None)
        if employee_branch:
            return getattr(employee_branch, "id", employee_branch)

    return None


def _normalize_requested_branch(value):
    if value in (None, "", "null", "undefined"):
        return None

    if str(value).lower() == "all":
        return "all"

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_queryset_by_branch_access(
    queryset,
    user,
    *,
    branch_field="branch",
    requested_branch_id=None,
):
    """
    Branch security rules:

    - Admin / branches.view_all:
      may view all branches or a selected specific branch.

    - branches.switch:
      may work in a selected specific branch, but "all" falls back to the
      user's assigned branch. This prevents an ordinary branch-switch user
      from bypassing branch scope by omitting the filter.

    - everyone else:
      is restricted to the assigned branch.
    """
    requested = _normalize_requested_branch(requested_branch_id)

    if can_view_all_branches(user):
        target_branch = None if requested in (None, "all") else requested
    elif can_switch_branches(user):
        target_branch = (
            requested if requested not in (None, "all") else get_user_branch_id(user)
        )
    else:
        target_branch = get_user_branch_id(user)

    if target_branch is None:
        return queryset if can_view_all_branches(user) else queryset.none()

    model = queryset.model

    try:
        model._meta.get_field(branch_field)
        return queryset.filter(**{f"{branch_field}_id": target_branch})
    except FieldDoesNotExist:
        pass

    candidate_paths = (
        f"{branch_field}_id",
        "employee__branch_id",
        "product_stock__branch_id",
        "payroll_run__branch_id",
        "sales_order__branch_id",
        "purchase_order__branch_id",
    )

    query = Q()
    matched = False

    for path in candidate_paths:
        root = path.split("__")[0]

        try:
            model._meta.get_field(root)
        except FieldDoesNotExist:
            continue

        query |= Q(**{path: target_branch})
        matched = True

    return queryset.filter(query) if matched else queryset


class BranchAccessQuerysetMixin:
    branch_field = "branch"
    enforce_branch_access = True

    def get_queryset(self):
        queryset = super().get_queryset()

        if not self.enforce_branch_access:
            return queryset

        requested_branch_id = self.request.query_params.get("branch")

        return filter_queryset_by_branch_access(
            queryset,
            self.request.user,
            branch_field=self.branch_field,
            requested_branch_id=requested_branch_id,
        )
