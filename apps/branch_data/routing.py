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
    value = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "VAT_BRANCH": VAT,
        "BR01": VAT,
        "NONVAT": NON_VAT,
        "NON_VAT_BRANCH": NON_VAT,
        "BR02": NON_VAT,
    }
    return aliases.get(value, value)


def source_for_active_branch(active_branch):
    code = normalize_branch_code(active_branch)
    return BRANCH_TO_SOURCE.get(code)


def database_for_source(source_branch):
    source = normalize_source(source_branch)
    try:
        return SOURCE_TO_ALIAS[source]
    except KeyError as exc:
        raise ValidationError(
            {"target_branch": "Target branch must be VAT or NON_VAT."}
        ) from exc


def real_branch_code_for_source(source_branch):
    source = normalize_source(source_branch)
    try:
        return SOURCE_TO_BRANCH_CODE[source]
    except KeyError as exc:
        raise ValidationError(
            {"target_branch": "Target branch must be VAT or NON_VAT."}
        ) from exc


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

    if active_source in {VAT, NON_VAT}:
        source = active_source
    elif active_source == COMBINED:
        source = normalize_source(target_branch) or get_request_target(request)
        if source not in {VAT, NON_VAT}:
            if write:
                raise ValidationError({
                    "target_branch": (
                        "Select VAT Branch or Non-VAT Branch before creating "
                        "a transaction from the Combined Branch."
                    )
                })
            raise ValidationError({
                "source_branch": "Select VAT, NON_VAT, or ALL for this operation."
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
    if source not in {VAT, NON_VAT}:
        raise ValueError("source_branch must be VAT or NON_VAT")
    return f"{source}:{record_id}"


def parse_resource_key(value):
    raw = str(value or "")
    if ":" not in raw:
        raise ValidationError({"id": "Expected composite id like VAT:15."})
    source, record_id = raw.split(":", 1)
    source = normalize_source(source)
    if source not in {VAT, NON_VAT}:
        raise ValidationError({"id": "Unknown source branch."})
    try:
        record_id = int(record_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"id": "Invalid record id."}) from exc
    return source, record_id
