from functools import lru_cache

from django.apps import apps
from django.conf import settings

MASTER_ALIAS = "default"
VAT_ALIAS = "vat"
NON_VAT_ALIAS = "non_vat"
VALID_DATABASE_ALIASES = {MASTER_ALIAS, VAT_ALIAS, NON_VAT_ALIAS}


def _normalize_branch_id(branch_or_id):
    value = getattr(branch_or_id, "pk", branch_or_id)

    if value in (None, "", "all", "ALL"):
        return None

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid branch id.") from exc


@lru_cache(maxsize=64)
def branch_database_info(branch_id):
    branch_id = _normalize_branch_id(branch_id)

    if branch_id is None:
        return {
            "branch_id": None,
            "mode": "MASTER",
            "database_alias": MASTER_ALIAS,
            "is_master_inventory": True,
            "show_combined_reports": True,
        }

    Profile = apps.get_model("branch_data", "BranchDatabaseProfile")
    profile = (
        Profile.objects.using("default")
        .filter(branch_id=branch_id, is_active=True)
        .values(
            "branch_id",
            "mode",
            "database_alias",
            "is_master_inventory",
            "show_combined_reports",
        )
        .first()
    )

    if profile:
        alias = profile.get("database_alias") or MASTER_ALIAS
        if alias not in VALID_DATABASE_ALIASES:
            raise RuntimeError(
                f"Unsupported database alias '{alias}' configured for branch {branch_id}."
            )
        if getattr(settings, "GHAZA_SCHEMA_WRITE_ROUTING", False) and profile["mode"] in {"VAT", "NON_VAT"}:
            from .schema_routing import register_branch_connection
            from .schema_routing import branch_alias
            _, expected_schema = branch_alias(branch_id, profile["mode"])
            from django.db import connections
            from django.core.exceptions import ImproperlyConfigured
            with connections[register_branch_connection(branch_id, profile["mode"])].cursor() as cursor:
                cursor.execute("SELECT current_schema(), to_regclass('inventory_productstock')")
                current, stock = cursor.fetchone()
            if current != expected_schema or stock is None:
                raise ImproperlyConfigured(f"Unprovisioned branch schema: {expected_schema}")
            return {**profile, "database_alias": register_branch_connection(branch_id, profile["mode"])}
        return profile

    # Additional physical branches share the VAT/Non-VAT database selected by
    # tax_mode. Business queries MUST be scoped to branch_id in that database.
    Branch = apps.get_model("branches", "Branch")
    branch = Branch.objects.using("default").filter(pk=branch_id, is_active=True).first()
    if branch and branch.tax_mode in {"VAT", "NON_VAT"} and not getattr(settings, "GHAZA_SCHEMA_WRITE_ROUTING", False):
        return {
            "branch_id": branch_id,
            "mode": branch.tax_mode,
            "database_alias": VAT_ALIAS if branch.tax_mode == "VAT" else NON_VAT_ALIAS,
            "is_master_inventory": False,
            "show_combined_reports": True,
        }

    if branch and getattr(settings, "GHAZA_SCHEMA_WRITE_ROUTING", False):
        # Explicitly fail closed; an active but unprovisioned tenant must not
        # silently use public tables or the default connection.
        raise RuntimeError(f"Branch {branch_id} lacks an active schema database profile")

    # Existing branches that do not have a special VAT/Non-VAT profile continue
    # to use the MASTER database rather than leaking into a secondary database.
    return {
        "branch_id": branch_id,
        "mode": "MASTER",
        "database_alias": MASTER_ALIAS,
        "is_master_inventory": False,
        "show_combined_reports": False,
    }


def database_alias_for_branch(branch_or_id):
    branch_id = _normalize_branch_id(branch_or_id)
    # The Supplier API is moved independently of the global ERP write-routing
    # rollout. Outside that request scope, preserve legacy behavior unchanged.
    from .supplier_scope import supplier_tenant_scope_active
    if branch_id is not None and supplier_tenant_scope_active():
        Branch = apps.get_model("branches", "Branch")
        if Branch.objects.using("default").filter(pk=branch_id, branch_code__iexact="CONSOLIDATED", is_active=True).exists():
            return MASTER_ALIAS
        from .schema_routing import register_branch_connection
        Branch = apps.get_model("branches", "Branch")
        branch = Branch.objects.using("default").filter(pk=branch_id, is_active=True).first()
        if branch and branch.tax_mode in {"VAT", "NON_VAT"}:
            return register_branch_connection(branch.pk, branch.tax_mode)
        raise ValueError("Supplier operations require an active physical branch.")
    return branch_database_info(branch_id)["database_alias"]


def mode_for_branch(branch_or_id):
    branch_id = _normalize_branch_id(branch_or_id)
    return branch_database_info(branch_id)["mode"]


def get_master_branch():
    Profile = apps.get_model("branch_data", "BranchDatabaseProfile")
    profile = (
        Profile.objects.using("default")
        .select_related("branch")
        .filter(is_master_inventory=True, is_active=True)
        .first()
    )

    if not profile:
        raise RuntimeError(
            "No Master Inventory branch configured. Run bootstrap_branch_databases."
        )

    return profile.branch


def inventory_branch_for(source_branch):
    if source_branch is None:
        return get_master_branch()

    info = branch_database_info(source_branch.pk)
    if info["is_master_inventory"]:
        return source_branch

    return get_master_branch()


def clear_branch_database_cache():
    branch_database_info.cache_clear()
