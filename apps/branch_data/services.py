from functools import lru_cache

from django.apps import apps

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
        return profile

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
