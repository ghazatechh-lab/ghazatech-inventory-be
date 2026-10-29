"""Explicit destructive reset for a development GhazaTech instance.

Does not alter application routing, DATABASES settings, Docker services, or migrations.
Requires the API and Celery services to be stopped externally.
"""
import re

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from apps.branches.models import Branch
from apps.branch_data.models import BranchDatabaseProfile
from apps.branch_data.services import clear_branch_database_cache

SCHEMA_RE = re.compile(r"^branch_[0-9]{8}$")
CONFIRMATION = "DELETE_ALL_BUSINESS_DATA"


class Command(BaseCommand):
    help = "DESTRUCTIVE: reset all branch and business records in default/vat/non_vat and tenant schemas, preserving one admin. Dry run by default."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="ghaza_test_admin")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["admin_username"]
        matches = list(User.objects.using("default").filter(username=username))
        if len(matches) != 1 or not matches[0].is_superuser or not matches[0].is_active:
            raise CommandError("Expected exactly one active superuser with the requested username in default.")
        admin = matches[0]
        # Concrete model fields only; preserve password hash and admin identity, but
        # clear all foreign keys to old business/role/employee/branch records.
        preserved = {}
        for field in User._meta.concrete_fields:
            if field.primary_key:
                continue
            if field.is_relation:
                if not field.null:
                    raise CommandError(f"Cannot safely reset required User FK {field.name}.")
                preserved[field.attname] = None
            else:
                preserved[field.attname] = getattr(admin, field.attname)

        schemas = {}
        for alias in ("vat", "non_vat"):
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'branch\\_%' ESCAPE '\\' ORDER BY schema_name")
                found = [r[0] for r in cursor.fetchall()]
            invalid = [s for s in found if not SCHEMA_RE.fullmatch(s)]
            if invalid:
                raise CommandError(f"Unexpected branch-like schemas in {alias}: {invalid}. Manual review required.")
            schemas[alias] = found

        self.stdout.write("Admin preserved: username=%s, id=%s (password hash retained; no password printed)" % (username, admin.pk))
        self.stdout.write("Physical schemas to DROP: %s" % schemas)
        self.stdout.write("Public application data to FLUSH: default, vat, non_vat")
        self.stdout.write("After reset, create single virtual branch: GhazaTech Consolidated [code=CONSOLIDATED]")
        if not options["apply"]:
            self.stdout.write("DRY RUN only. No data modified. Run with --apply --confirm %s to proceed." % CONFIRMATION)
            return
        if options["confirm"] != CONFIRMATION:
            raise CommandError("Refusing destructive reset without --confirm %s" % CONFIRMATION)

        # No cross-database atomic transactions exist. Stopped workers/API are mandatory.
        for alias in ("vat", "non_vat"):
            with connections[alias].cursor() as cursor:
                for schema in schemas[alias]:
                    cursor.execute(f'DROP SCHEMA "{schema}" CASCADE')
                    self.stdout.write(f"Dropped {alias}.{schema}")
            call_command("flush", database=alias, interactive=False, verbosity=0)
            self.stdout.write(f"Flushed {alias}.public")

        # Preserve admin in memory while the default public schema is flushed.
        call_command("flush", database="default", interactive=False, verbosity=0)
        with transaction.atomic(using="default"):
            User.objects.using("default").create(pk=admin.pk, **preserved)
            Branch.objects.using("default").create(
                branch_code="CONSOLIDATED", branch_name="GhazaTech Consolidated",
                branch_type="MASTER", tax_mode="", is_active=True,
            )
            virtual = Branch.objects.using("default").get(branch_code="CONSOLIDATED")
            BranchDatabaseProfile.objects.using("default").create(
                branch=virtual, mode="MASTER", database_alias="default",
                schema_name="", is_master_inventory=True,
                show_combined_reports=True, is_active=True,
            )
            with connections["default"].cursor() as cursor:
                for table in ("accounts_user", "branches_branch", "branch_data_branchdatabaseprofile"):
                    cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [table])
                    seq = cursor.fetchone()[0]
                    if seq:
                        cursor.execute(f'SELECT setval(%s, COALESCE((SELECT MAX(id) FROM "{table}"), 1), (SELECT COUNT(*) > 0 FROM "{table}"))', [seq])
        clear_branch_database_cache()
        self.stdout.write(self.style.SUCCESS("RESET COMPLETE: one admin preserved and GhazaTech Consolidated created."))
        self.stdout.write("WARNING: Schema-aware routing and all-module consolidated views remain unfinished. Keep live business transactions disabled.")
