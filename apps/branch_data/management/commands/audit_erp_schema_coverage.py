"""Read-only report of app routing with a physical branch context.

This is a diagnostic aid, not proof that explicit .using() calls and nested
serializer saves are tenant-safe. Never enables live routing.
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import router
from django.test.utils import override_settings

from apps.branches.models import Branch
from apps.branch_data.context import set_active_branch_id, reset_active_branch_id
from apps.branch_data.schema_routing import register_branch_connection
from apps.branch_data.services import clear_branch_database_cache


class Command(BaseCommand):
    help = "Audit ORM model routing for one provisioned branch (no writes)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)

    def handle(self, *args, **options):
        branch = Branch.objects.using("default").filter(pk=options["branch_id"], is_active=True).first()
        if not branch or branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("Choose an active physical VAT/NON_VAT branch")
        expected = register_branch_connection(branch.pk, branch.tax_mode)
        branch_owned = {"inventory", "sales", "purchases", "customers", "suppliers", "finance",
                        "shipments", "transfers", "hrms", "fleet", "service_repairs", "recovery"}
        token = set_active_branch_id(branch.pk)
        checked = 0
        unexpected = []
        try:
            with override_settings(GHAZA_SCHEMA_WRITE_ROUTING=True):
                clear_branch_database_cache()
                for model in apps.get_models():
                    if model._meta.app_label not in branch_owned or model._meta.proxy:
                        continue
                    read = router.db_for_read(model)
                    write = router.db_for_write(model)
                    checked += 1
                    if read != expected or write != expected:
                        unexpected.append((model._meta.label, read, write))
        finally:
            reset_active_branch_id(token)
            clear_branch_database_cache()
        self.stdout.write(f"branch={branch.pk}, tenant={expected}, models={checked}, unexpected={len(unexpected)}")
        for name, read, write in unexpected:
            self.stdout.write(f"  {name}: read={read}, write={write}")
        self.stdout.write("NOTE: Router coverage does not validate explicit .using(), SQL, Celery, or combined views.")
        if unexpected:
            raise CommandError("Some branch-owned models do not route to this tenant alias")
