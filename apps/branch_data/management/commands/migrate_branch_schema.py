"""Create and migrate one branch schema on its selected VAT/NON-VAT database.

This is an explicit administrative operation. It does not switch live request
routing or delete any records. Execute only after reviewing the migration plan.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.branches.models import Branch
from apps.branch_data.schema_routing import branch_alias, register_branch_connection

# Presence checks do not prove end-to-end ERP support, but fail on empty schemas.
REQUIRED_TABLES = {
    "django_migrations", "branches_branch", "accounts_user",
    "inventory_product", "inventory_productstock", "sales_salesinvoice",
    "purchases_purchaseorder",
}


class Command(BaseCommand):
    help = "Migrate a physical branch schema (dry run by default; no live routing switch)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)
        parser.add_argument("--apply", action="store_true", help="Create schema and run migrations")

    def handle(self, *args, **options):
        branch = Branch.objects.using("default").filter(pk=options["branch_id"]).first()
        if branch is None:
            raise CommandError("Branch not found")
        if branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("The consolidated branch cannot own a physical schema")

        base, schema = branch_alias(branch.pk, branch.tax_mode)
        alias = register_branch_connection(branch.pk, branch.tax_mode)
        self.stdout.write(f"Branch {branch.pk} ({branch.branch_name}) -> {base}.{schema} [{alias}]")
        if not options["apply"]:
            self.stdout.write("DRY RUN: no changes. Add --apply to create schema and apply migrations.")
            return

        with connections[base].cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        # Never fall back to public if schema doesn't resolve.
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT current_schema()")
            actual = cursor.fetchone()[0]
        if actual != schema:
            raise CommandError(f"Unsafe tenant search_path: expected {schema}, got {actual!r}")

        # Django migration executor respects router.allow_migrate for tenant aliases.
        call_command("migrate", database=alias, interactive=False, verbosity=1)
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = %s", [schema])
            tables = {row[0] for row in cursor.fetchall()}
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise CommandError(f"Schema migrated but required tables are missing: {', '.join(missing)}")
        self.stdout.write(self.style.SUCCESS(f"Schema {base}.{schema} contains required tables"))
        self.stdout.write("NOT ACTIVE FOR TRANSACTIONS: reference records, cross-module routing, and combined views still require integration.")
