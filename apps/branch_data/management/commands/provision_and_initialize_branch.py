"""Provision a migrated schema and minimal references for one already-created branch.

Do not activate cross-module routing automatically. Database DDL is not transactionally
atomic with writes to the shared control database.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from apps.branches.models import Branch
from apps.branch_data.schema_routing import branch_alias, register_branch_connection


class Command(BaseCommand):
    help = "Provision a physical branch schema and initialize minimal references (dry run default)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        branch = Branch.objects.using("default").filter(pk=opts["branch_id"]).first()
        if not branch or branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("Existing physical VAT/NON_VAT branch required")
        if not branch.is_active:
            raise CommandError("Branch is inactive; current initializer requires an active branch")
        base, schema = branch_alias(branch.pk, branch.tax_mode)
        self.stdout.write(f"Target: {base}.{schema} ({branch.branch_name})")
        if not opts["apply"]:
            self.stdout.write("DRY RUN. --apply runs schema migrations and initializes references.")
            return
        call_command("migrate_branch_schema", branch.pk, apply=True)
        call_command("initialize_branch_schema", branch.pk, apply=True)
        alias = register_branch_connection(branch.pk, branch.tax_mode)
        with connections[alias].cursor() as c:
            c.execute("SELECT current_schema()")
            if c.fetchone()[0] != schema:
                raise CommandError("Unsafe schema search path")
            c.execute("SELECT COUNT(*) FROM branches_branch WHERE id = %s", [branch.pk])
            if c.fetchone()[0] != 1:
                raise CommandError("Branch reference missing after initialization")
        self.stdout.write(self.style.SUCCESS("Provisioned, migrated and initialized. Live routing is NOT enabled."))
