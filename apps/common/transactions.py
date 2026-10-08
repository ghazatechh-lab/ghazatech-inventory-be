from functools import wraps

from django.db import transaction

from apps.branch_data.context import get_active_branch_id
from apps.branch_data.routing import database_for_source, normalize_source
from apps.branch_data.services import database_alias_for_branch


def _branch_id_from_value(value):
    if value is None:
        return None
    if hasattr(value, "pk"):
        return value.pk
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _alias_from_instance(value):
    if value is None:
        return None
    meta = getattr(value, "_meta", None)
    if getattr(meta, "model_name", "") == "branch":
        branch_id = getattr(value, "pk", None)
        return database_alias_for_branch(branch_id) if branch_id else None
    branch_id = getattr(value, "branch_id", None)
    if branch_id:
        return database_alias_for_branch(branch_id)
    return getattr(getattr(value, "_state", None), "db", None)


def _request_from_args(args, kwargs):
    # DRF ViewSet method: (self, request, ...)
    if len(args) > 1 and hasattr(args[1], "data") and hasattr(args[1], "headers"):
        return args[1]

    owner = args[0] if args else None
    context = getattr(owner, "context", None) or {}
    request = context.get("request") if isinstance(context, dict) else None
    if request is not None:
        return request
    return kwargs.get("request")


def resolve_transaction_alias(args, kwargs):
    owner = args[0] if args else None

    # Existing model instances already know which database they came from.
    candidates = [
        kwargs.get("instance"),
        getattr(owner, "instance", None),
    ]
    if len(args) > 1 and hasattr(args[1], "_state"):
        candidates.append(args[1])
    for instance in candidates:
        alias = _alias_from_instance(instance)
        if alias:
            return alias

    # Service functions often receive branch or a branch-aware document directly.
    branch_id = _branch_id_from_value(kwargs.get("branch"))
    if branch_id:
        return database_alias_for_branch(branch_id)
    for value in args:
        alias = _alias_from_instance(value)
        if alias:
            return alias

    # Serializer create/update validated_data usually carries the physical branch.
    validated_data = kwargs.get("validated_data")
    if validated_data is None and len(args) > 1 and isinstance(args[1], dict):
        validated_data = args[1]
    if isinstance(validated_data, dict):
        branch_id = _branch_id_from_value(validated_data.get("branch"))
        if branch_id:
            return database_alias_for_branch(branch_id)

    request = _request_from_args(args, kwargs)
    if request is not None:
        data = getattr(request, "data", {}) or {}
        query = getattr(request, "query_params", {}) or {}
        headers = getattr(request, "headers", {}) or {}

        target = normalize_source(
            data.get("target_branch")
            or query.get("target_branch")
            or headers.get("X-Target-Branch")
        )
        if target in {"VAT", "NON_VAT"}:
            return database_for_source(target)

        branch_id = _branch_id_from_value(data.get("branch"))
        if branch_id:
            return database_alias_for_branch(branch_id)

    active_branch_id = get_active_branch_id()
    if active_branch_id:
        return database_alias_for_branch(active_branch_id)

    return "default"


def routed_atomic(func):
    """Run a unit of work in the database selected by branch routing.

    Django's bare @transaction.atomic always targets ``default``. A row lock on
    ``vat`` or ``non_vat`` is therefore *not* protected by that transaction.
    This decorator binds the atomic block to the same routed database.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        using = resolve_transaction_alias(args, kwargs)
        with transaction.atomic(using=using):
            return func(*args, **kwargs)

    return wrapper
