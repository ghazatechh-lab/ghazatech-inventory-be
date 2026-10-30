from dataclasses import dataclass

from rest_framework.exceptions import PermissionDenied, ValidationError

VAT = "VAT"
NON_VAT = "NON_VAT"
COMBINED = "COMBINED"

VAT_ALIAS = "vat"
NON_VAT_ALIAS = "non_vat"

BR01 = "BR01"
BR02 = "BR02"
BR03 = "BR03"
CONSOLIDATED = "CONSOLIDATED"

SOURCE_TO_ALIAS = {
    VAT: VAT_ALIAS,
    NON_VAT: NON_VAT_ALIAS,
}

SOURCE_TO_BRANCH_CODE = {
    VAT: BR01,
    NON_VAT: BR02,
}

BRANCH_TO_SOURCE = {
    BR01: VAT,
    BR02: NON_VAT,
    BR03: COMBINED,
    CONSOLIDATED: CONSOLIDATED,
}


@dataclass(frozen=True)
class OperationContext:
    active_branch_code: str
    source_branch: str
    db_alias: str
    real_branch_code: str
    combined_access: bool = False


def normalize_branch_code(value):
    if value is None:
        return ""
    if hasattr(value, "branch_code"):
        value = value.branch_code
    return str(value).strip().upper()


def normalize_source(value):
    """Normalize aliases without changing actual physical branch codes."""
    raw = str(value or "").strip().upper()

    aliases = {
        "VAT_BRANCH": VAT,
        "VAT-BRANCH": VAT,
        "BR01": VAT,
        "NONVAT": NON_VAT,
        "NON-VAT": NON_VAT,
        "NON_VAT_BRANCH": NON_VAT,
        "NON-VAT-BRANCH": NON_VAT,
        "BR02": NON_VAT,
    }

    return aliases.get(raw, raw)



def _physical_from_source(source):
    from apps.branches.models import Branch
    from django.db.models import Q
    source = normalize_source(source)
    qs = Branch.objects.using("default").filter(is_active=True)
    if source == CONSOLIDATED:
        return qs.filter(branch_code__iexact=CONSOLIDATED).first()
    qs = qs.filter(tax_mode__in=(VAT, NON_VAT))
    if source.isdigit():
        return qs.filter(pk=int(source)).first()
    branch = qs.filter(branch_code__iexact=source).first()
    if branch:
        return branch
    if source in (VAT, NON_VAT):
        matches = list(qs.filter(tax_mode=source)[:2])
        # A tax classification does not select a unique branch when multiple
        # locations use the same tax treatment.
        if len(matches) == 1:
            return matches[0]
    return None


def source_for_active_branch(active_branch):
    code = normalize_branch_code(active_branch)
    from apps.branches.models import Branch
    branch = (Branch.objects.using("default").filter(pk=int(code)).first()
              if code.isdigit() else Branch.objects.using("default").filter(branch_code__iexact=code).first())
    if branch and branch.is_active:
        if branch.branch_code.upper() == CONSOLIDATED:
            return CONSOLIDATED
        if branch.tax_mode in {VAT, NON_VAT}:
            return branch.branch_code.upper()
        if branch.branch_type == "MASTER":
            return COMBINED
    return None


def database_for_source(source_branch):
    from apps.branch_data.services import database_alias_for_branch
    branch = _physical_from_source(source_branch)
    if branch is None:
        raise ValidationError({"target_branch": "Select a unique active physical branch."})
    return database_alias_for_branch(branch.pk)


def real_branch_code_for_source(source_branch):
    branch = _physical_from_source(source_branch)
    if branch is None:
        raise ValidationError({"target_branch": "Select a unique active physical branch."})
    return branch.branch_code.upper()


def get_request_target(request):
    if request is None:
        return ""
    data = getattr(request, "data", {}) or {}
    query = getattr(request, "query_params", {}) or {}
    headers = getattr(request, "headers", {}) or {}
    return normalize_source(
        data.get("target_branch")
        or data.get("sale_mode")
        or query.get("target_branch")
        or query.get("source_branch")
        or headers.get("X-Target-Branch")
    )


def resolve_operation_context(
    *,
    active_branch,
    target_branch=None,
    request=None,
    permission_checker=None,
    write=False,
):
    active_code = normalize_branch_code(active_branch)
    active_source = source_for_active_branch(active_code)

    if active_source and active_source != COMBINED:
        source = active_source
    elif active_source == COMBINED:
        source = normalize_source(target_branch) or get_request_target(request)
        if _physical_from_source(source) is None:
            if write:
                raise ValidationError({
                    "target_branch": (
                        "Select a specific physical branch before creating "
                        "a transaction from GhazaTech Consolidated."
                    )
                })
            raise ValidationError({
                "source_branch": "Select a specific physical branch for this operation."
            })
    else:
        raise ValidationError({"branch": "Unsupported active branch."})

    if permission_checker is not None:
        allowed = permission_checker(source, write=write)
        if not allowed:
            raise PermissionDenied(
                f"You do not have permission for {source} operations."
            )

    return OperationContext(
        active_branch_code=active_code,
        source_branch=source,
        db_alias=database_for_source(source),
        real_branch_code=real_branch_code_for_source(source),
        combined_access=(active_source == COMBINED),
    )


def make_resource_key(source_branch, record_id):
    source = normalize_source(source_branch)
    if _physical_from_source(source) is None:
        raise ValueError("source_branch must identify an active physical branch")
    return f"{source}:{record_id}"


def parse_resource_key(value):
    raw = str(value or "")
    if ":" not in raw:
        raise ValidationError({"id": "Expected composite id like VAT:15."})
    source, record_id = raw.split(":", 1)
    source = normalize_source(source)
    if _physical_from_source(source) is None:
        raise ValidationError({"id": "Unknown source branch."})
    try:
        record_id = int(record_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"id": "Invalid record id."}) from exc
    return source, record_id
