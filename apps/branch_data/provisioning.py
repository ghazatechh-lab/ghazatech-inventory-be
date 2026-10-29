"""Explicit, idempotent schema provisioning for VAT / NON_VAT branches.

This is not a global transaction: PostgreSQL DDL and the control database cannot
commit atomically together. Failed provisioning keeps the branch disabled.
"""
from django.core.management import call_command
from django.db import connections, transaction

from apps.branch_data.models import BranchDatabaseProfile
from apps.branch_data.schema_routing import branch_alias, register_branch_connection
from apps.branch_data.services import clear_branch_database_cache
from apps.branches.models import Branch


def provision_physical_branch(branch_id):
    branch = Branch.objects.using("default").get(pk=branch_id)
    if branch.tax_mode not in {"VAT", "NON_VAT"}:
        raise ValueError("Only VAT/NON_VAT physical branches can be provisioned")

    base, schema = branch_alias(branch.pk, branch.tax_mode)
    expected = {"mode": branch.tax_mode, "database_alias": base, "schema_name": schema}
    existing = BranchDatabaseProfile.objects.using("default").filter(branch_id=branch.pk).first()
    if existing:
        # Profiles created before per-branch schemas were introduced have an
        # empty schema_name. Treat that as unassigned, not as a conflict.
        # Never reassign a profile already tied to a different physical schema.
        conflicting = (
            existing.mode != branch.tax_mode
            or existing.database_alias != base
            or existing.schema_name not in ("", schema)
            or existing.is_master_inventory
        )
        if conflicting:
            raise ValueError(
                "Existing branch profile conflicts with requested tax database or schema"
            )

    # Legacy initialization requires the branch to be active momentarily.
    Branch.objects.using("default").filter(pk=branch.pk).update(is_active=True)
    try:
        call_command("migrate_branch_schema", branch.pk, apply=True)
        call_command("initialize_branch_schema", branch.pk, apply=True)
        alias = register_branch_connection(branch.pk, branch.tax_mode)
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT current_schema(), to_regclass('branches_branch'), "
                           "to_regclass('accounts_user'), to_regclass('inventory_productstock')")
            actual, b_table, u_table, stock_table = cursor.fetchone()
            if actual != schema or not all((b_table, u_table, stock_table)):
                raise RuntimeError("Tenant schema verification failed")
            cursor.execute('SELECT EXISTS(SELECT 1 FROM branches_branch WHERE id = %s)', [branch.pk])
            if not cursor.fetchone()[0]:
                raise RuntimeError("Tenant branch reference is missing")
        with transaction.atomic(using="default"):
            BranchDatabaseProfile.objects.using("default").update_or_create(
                branch_id=branch.pk,
                defaults={**expected, "is_master_inventory": False,
                          "show_combined_reports": True, "is_active": True},
            )
            Branch.objects.using("default").filter(pk=branch.pk).update(is_active=True)
        clear_branch_database_cache()
    except Exception:
        Branch.objects.using("default").filter(pk=branch.pk).update(is_active=False)
        BranchDatabaseProfile.objects.using("default").filter(branch_id=branch.pk).update(is_active=False)
        clear_branch_database_cache()
        raise
    return base, schema
