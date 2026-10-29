"""Read-only tenant routing audit; never switches production feature flags."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, router
from django.test.utils import override_settings

from apps.branches.models import Branch
from apps.branch_data.context import reset_active_branch_id, set_active_branch_id
from apps.branch_data.schema_routing import register_branch_connection
from apps.branch_data.services import clear_branch_database_cache


class Command(BaseCommand):
    help = "Read-only audit of intended schema routing for a physical branch (no writes)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)

    def handle(self, *args, **options):
        branch = Branch.objects.using("default").filter(pk=options["branch_id"]).first()
        if not branch or not branch.is_active or branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("Choose an active physical VAT/NON_VAT branch")
        expected = register_branch_connection(branch.pk, branch.tax_mode)
        models = [
            ("inventory", "ProductStock"),
            ("sales", "SalesInvoice"),
            ("purchases", "PurchaseOrder"),
        ]
        from django.apps import apps
        self.stdout.write(f"Branch {branch.pk} {branch.branch_name}: expected={expected}")
        token = set_active_branch_id(branch.pk)
        try:
            with override_settings(GHAZA_SCHEMA_WRITE_ROUTING=True):
                clear_branch_database_cache()
                for app_label, model_name in models:
                    model = apps.get_model(app_label, model_name)
                    read_alias = router.db_for_read(model)
                    write_alias = router.db_for_write(model)
                    self.stdout.write(f"{app_label}.{model_name}: read={read_alias}, write={write_alias}")
                    if read_alias != expected or write_alias != expected:
                        raise CommandError(f"Unexpected alias for {app_label}.{model_name}")
                with connections[expected].cursor() as cur:
                    cur.execute("SELECT current_schema(), to_regclass('inventory_productstock')")
                    schema, table = cur.fetchone()
                if schema != f"branch_{branch.pk:08d}" or table is None:
                    raise CommandError(f"Schema/table mismatch: {schema}, {table}")
                self.stdout.write(self.style.SUCCESS(f"PASS: {expected} uses {schema} with required tables"))
        finally:
            reset_active_branch_id(token)
            clear_branch_database_cache()
        self.stdout.write(f"Live feature flag remains {'ON' if getattr(settings, 'GHAZA_SCHEMA_WRITE_ROUTING', False) else 'OFF'}. No records written.")
