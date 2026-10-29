"""Read-only audit of configured branch schemas, readiness and table counts."""
from django.core.management.base import BaseCommand
from django.db import connections
from apps.branches.models import Branch
from apps.branch_data.schema_routing import branch_alias


class Command(BaseCommand):
    help = "Audit physical branches and their PostgreSQL schemas (read-only)."

    def handle(self, *args, **options):
        for branch in Branch.objects.using("default").order_by("id"):
            if branch.tax_mode not in ("VAT", "NON_VAT"):
                self.stdout.write(f"{branch.pk} {branch.branch_name}: VIRTUAL/UNCLASSIFIED")
                continue
            alias, schema = branch_alias(branch.pk, branch.tax_mode)
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)", [schema])
                exists = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s", [schema])
                count = cursor.fetchone()[0]
            self.stdout.write(f"{branch.pk} {branch.branch_name}: {alias}.{schema}, schema_exists={exists}, tables={count}, active={branch.is_active}")
