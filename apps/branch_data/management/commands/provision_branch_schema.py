"""Create an isolated PostgreSQL schema for a physical branch.

Infrastructure-only. Does NOT install ERP tables or activate the branch.
Use after branch metadata and routing migrations are implemented.
"""
import re
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from apps.branches.models import Branch

VALID_SCHEMA = re.compile(r"^branch_[0-9a-z_]{1,48}$")

class Command(BaseCommand):
    help = "Provision a physical branch PostgreSQL schema (infrastructure only)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)
        parser.add_argument("--apply", action="store_true", help="Actually create schema")

    def handle(self, *args, **opts):
        branch = Branch.objects.using("default").filter(pk=opts["branch_id"]).first()
        if not branch:
            raise CommandError("Branch not found in default database")
        if branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("A physical branch must have a valid VAT/NON_VAT classification")
        from apps.branch_data.models import BranchDatabaseProfile
        if BranchDatabaseProfile.objects.using("default").filter(branch_id=branch.pk, is_master_inventory=True).exists():
            raise CommandError("Cannot provision a schema for the combined branch")
        alias = "vat" if branch.tax_mode == "VAT" else "non_vat"
        schema = f"branch_{branch.pk:08d}"
        if not VALID_SCHEMA.fullmatch(schema):
            raise CommandError("Unsafe schema identifier")
        self.stdout.write(f"Target: database alias={alias}, schema={schema}, branch={branch.branch_name}")
        self.stdout.write("This command does NOT migrate tables, route requests, or activate the branch")
        if not opts["apply"]:
            self.stdout.write("Dry run. Add --apply to create the schema.")
            return
        connection = connections[alias]
        with connection.cursor() as cursor:
            # Identifier is validated and generated from an integer primary key.
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        self.stdout.write(self.style.SUCCESS(f"Created or verified schema {schema} on {alias}"))
        self.stdout.write("Schema is EMPTY. Do not activate or write transactions until its migrations and reference data are installed.")
