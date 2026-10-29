"""Read-only, database-backed tenant isolation audit. No application data is written."""
from pathlib import Path
import re
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, router
from django.test.utils import override_settings
from apps.branches.models import Branch
from apps.branch_data.context import set_active_branch_id, reset_active_branch_id
from apps.branch_data.schema_routing import register_branch_connection, branch_alias
from apps.branch_data.services import clear_branch_database_cache

OWNED_APPS = frozenset({"inventory", "sales", "purchases", "customers", "suppliers", "finance", "shipments", "transfers", "hrms", "fleet", "service_repairs", "recovery"})
CHECK_TABLES = ("inventory_productstock", "sales_salesinvoice", "purchases_purchaseorder")

class Command(BaseCommand):
    help = "Read-only PostgreSQL schema isolation and ORM routing audit for all active physical branches."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Fail on any explicit public database alias hit in business app source")

    def handle(self, *args, **options):
        branches = list(Branch.objects.using("default").filter(is_active=True, tax_mode__in=("VAT", "NON_VAT")).order_by("pk"))
        if not branches:
            raise CommandError("No active physical branches to audit")
        failures = []
        seen = set()
        for branch in branches:
            base, schema = branch_alias(branch.pk, branch.tax_mode)
            alias = register_branch_connection(branch.pk, branch.tax_mode)
            if (base, schema) in seen:
                failures.append(f"Duplicate physical storage: {base}.{schema}")
            seen.add((base,schema))
            with connections[alias].cursor() as cur:
                cur.execute("SELECT current_schema(), current_database()")
                current_schema, dbname = cur.fetchone()
                cur.execute("SELECT to_regclass(%s), to_regclass(%s), to_regclass(%s)", CHECK_TABLES)
                tables = cur.fetchone()
                cur.execute("SELECT COUNT(*) FROM branches_branch WHERE id = %s", [branch.pk])
                branch_ref_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM accounts_user WHERE is_superuser AND is_active")
                admins = cur.fetchone()[0]
            token=set_active_branch_id(branch.pk)
            try:
                with override_settings(GHAZA_SCHEMA_WRITE_ROUTING=True):
                    clear_branch_database_cache()
                    wrong=[]; n=0
                    for model in apps.get_models():
                        if model._meta.app_label not in OWNED_APPS or model._meta.proxy:
                            continue
                        n+=1
                        rd=router.db_for_read(model)
                        wr=router.db_for_write(model)
                        if rd != alias or wr != alias:
                            wrong.append(f"{model._meta.label}: read={rd} write={wr}")
            finally:
                reset_active_branch_id(token)
                clear_branch_database_cache()
            self.stdout.write(f"{branch.pk} {branch.branch_name}: {base}.{schema} alias={alias} database={dbname}; models={n}; refs={branch_ref_count} admins={admins}; missing_tables={sum(x is None for x in tables)}; wrong_routes={len(wrong)}")
            if current_schema != schema:
                failures.append(f"Branch {branch.pk}: connected to {current_schema!r} rather than {schema!r}")
            if any(x is None for x in tables):
                failures.append(f"Branch {branch.pk}: missing core tables")
            if branch_ref_count != 1 or not admins:
                failures.append(f"Branch {branch.pk}: missing branch/admin reference")
            failures.extend(wrong)
        # Detect source code bypasses without assuming all are unsafe.
        root=Path(__file__).resolve().parents[3]
        matches=[]
        for app in OWNED_APPS:
            folder=root/app
            if not folder.exists():
                continue
            for file in folder.rglob("*.py"):
                if "migrations" in file.parts or "tests" in file.name:
                    continue
                for num,line in enumerate(file.read_text(errors="replace").splitlines(),1):
                    if re.search(r"\.using\s*\(\s*['\"](?:default|vat|non_vat)['\"]|\.db_manager\s*\(\s*['\"](?:default|vat|non_vat)['\"]",line):
                        matches.append(f"{file.relative_to(root)}:{num}: {line.strip()[:135]}")
        self.stdout.write(f"Explicit literal database alias calls in branch-owned apps: {len(matches)}")
        for match in matches[:35]:
            self.stdout.write("  " + match)
        if len(matches)>35:
            self.stdout.write(f"  ... {len(matches)-35} more; search source for .using() and .db_manager()")
        if options["strict"] and matches:
            failures.append(f"{len(matches)} explicit database aliases require manual assessment")
        if failures:
            for failure in failures[:30]:
                self.stderr.write("FAIL: " + failure)
            raise CommandError(f"Tenant isolation audit failed: {len(failures)} findings")
        self.stdout.write(self.style.SUCCESS("PASS: schema placement, references, and ORM model routing validated (read-only)."))
        if matches:
            self.stdout.write("WARNING: explicit database calls remain; do not enable live writes on this audit alone.")
