"""Seed minimal branch and active-admin references into a migrated tenant schema.

Does not modify global auth, copy business data, or enable live tenant routing.
Dry-run unless --apply. Run only after migrate_branch_schema <id> --apply.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from apps.branches.models import Branch
from apps.branch_data.schema_routing import branch_alias, register_branch_connection


def values_without_relations(instance, *, exclude=()):
    result = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.name in exclude:
            continue
        if field.is_relation:
            if not field.null:
                raise CommandError(
                    f"Cannot initialize {instance._meta.label}.{field.name}: required relation"
                )
            result[field.attname] = None
        else:
            result[field.attname] = getattr(instance, field.attname)
    return result


class Command(BaseCommand):
    help = "Initialize branch and active superuser references in a migrated branch schema (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("branch_id", type=int)
        parser.add_argument("--apply", action="store_true", help="Write minimal reference rows to the branch schema")

    def handle(self, *args, **options):
        branch_id = options["branch_id"]
        branch = Branch.objects.using("default").filter(pk=branch_id).first()
        if branch is None:
            raise CommandError("Branch not found in default database")
        if branch.tax_mode not in {"VAT", "NON_VAT"}:
            raise CommandError("Only VAT or NON_VAT physical branches can be initialized")
        if not branch.is_active:
            raise CommandError("Inactive branch: activate after provisioning policy is configured")

        User = get_user_model()
        admins = list(User.objects.using("default").filter(is_active=True, is_superuser=True).order_by("pk"))
        if not admins:
            raise CommandError("No active superuser exists in the default database")
        base, schema = branch_alias(branch.pk, branch.tax_mode)
        alias = register_branch_connection(branch.pk, branch.tax_mode)
        self.stdout.write(f"Target: {base}.{schema} (alias={alias})")
        self.stdout.write(f"Branch reference: {branch.pk} {branch.branch_name}; active admin accounts: {len(admins)}")
        if not options["apply"]:
            self.stdout.write("DRY RUN: no records inserted. Run with --apply to initialize.")
            return

        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT current_schema()")
            actual = cursor.fetchone()[0]
            if actual != schema:
                raise CommandError(f"Unsafe search_path: expected {schema}, got {actual!r}")
            cursor.execute("SELECT to_regclass('branches_branch'), to_regclass('accounts_user')")
            if any(value is None for value in cursor.fetchone()):
                raise CommandError("Required tenant tables not found; run migrate_branch_schema first")

        with transaction.atomic(using=alias):
            existing_branch = Branch.objects.using(alias).filter(pk=branch.pk).first()
            if existing_branch and existing_branch.branch_code != branch.branch_code:
                raise CommandError("Branch primary-key collision in target schema")
            branch_defaults = values_without_relations(branch)
            Branch.objects.using(alias).update_or_create(pk=branch.pk, defaults=branch_defaults)

            for admin in admins:
                existing = User.objects.using(alias).filter(pk=admin.pk).first()
                if existing and (existing.email != admin.email or not existing.is_superuser):
                    raise CommandError(f"Admin primary-key collision for user ID {admin.pk}")
                user_defaults = values_without_relations(admin)
                # Auth identity is controlled by default; preserve hash, not plaintext.
                User.objects.using(alias).update_or_create(pk=admin.pk, defaults=user_defaults)

            # Explicit primary keys do not advance PostgreSQL identity sequences.
            with connections[alias].cursor() as cursor:
                for table in ("branches_branch", "accounts_user"):
                    cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [table])
                    sequence = cursor.fetchone()[0]
                    if sequence:
                        cursor.execute(
                            f'SELECT setval(%s, COALESCE((SELECT MAX(id) FROM "{table}"), 1), '
                            f'(SELECT COUNT(*) > 0 FROM "{table}"))',
                            [sequence],
                        )

        self.stdout.write(self.style.SUCCESS(
            f"Initialized {base}.{schema}: branch={branch.pk}, active admins={len(admins)}"
        ))
        self.stdout.write("Transaction routing and consolidated reporting remain disabled; do not use this as go-live approval.")
