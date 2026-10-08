from rest_framework import serializers

from apps.branches.models import Branch

PHYSICAL_BRANCH_CODES = {"BR01", "BR02"}
COMBINED_BRANCH_CODE = "BR03"


def is_physical_branch(branch):
    return bool(branch and str(getattr(branch, "branch_code", "")).upper() in PHYSICAL_BRANCH_CODES)


def require_physical_branch(branch, *, field="branch", message=None):
    if not is_physical_branch(branch):
        raise serializers.ValidationError({
            field: message or "Select Branch 1 or Branch 2. Branch 3 is a combined interface and cannot own physical inventory."
        })
    return branch


def request_active_branch(request):
    """Resolve the currently selected branch to the canonical default DB row.

    The frontend may send the branch as a numeric ID or a branch code.  Always
    normalize it against the shared/default branches table before comparisons,
    because physical databases may contain mirrored branch rows with different
    object instances.
    """
    if request is None:
        return None

    query = getattr(request, "query_params", {}) or {}
    headers = getattr(request, "headers", {}) or {}
    data = getattr(request, "data", {}) or {}

    value = (
        query.get("branch")
        or query.get("branch_id")
        or headers.get("X-Branch-ID")
        or headers.get("X-Branch-Id")
        or headers.get("X-Branch-Code")
        or data.get("branch")
        or data.get("branch_id")
        or data.get("physical_branch")
    )

    if value in (None, ""):
        return None

    # Objects/dicts can occasionally be passed by internal callers.
    if isinstance(value, dict):
        value = value.get("id") or value.get("branch_id") or value.get("branch_code")
    else:
        value = getattr(value, "pk", None) or getattr(value, "branch_code", None) or value

    manager = Branch.objects.using("default")
    normalized = str(value).strip()

    if normalized.isdigit():
        try:
            return manager.get(pk=int(normalized))
        except Branch.DoesNotExist:
            return None

    code = normalized.upper()
    if code in {"BR01", "BR02", "BR03"}:
        try:
            return manager.get(branch_code=code)
        except Branch.DoesNotExist:
            return None

    return None
