"""Replace the legacy consolidated branch with one writable single-DB branch."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth import get_user_model
from apps.branches.models import Branch
from apps.branch_data.models import BranchDatabaseProfile
from apps.branch_data.services import clear_branch_database_cache

class Command(BaseCommand):
    help = "Provision one consolidated physical branch in default.public; preserves the admin."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        User = get_user_model()
        qs = Branch.objects.using("default")
        profiles = BranchDatabaseProfile.objects.using("default")
        admin = User.objects.using("default").filter(pk=1, username="admin", email="admin@ghazatech.com", is_superuser=True, is_active=True).first()
        if not admin:
            raise CommandError("Expected active admin user ID 1")
        existing = list(qs.values_list("pk", "branch_code"))
        if len(existing) != 1 or existing[0][1] != "CONSOLIDATED":
            raise CommandError(f"Expected one existing CONSOLIDATED branch; got {existing}")
        old_id = existing[0][0]
        if profiles.count() != 1 or not profiles.filter(branch_id=old_id, database_alias="default").exists():
            raise CommandError("Unexpected branch profiles")
        self.stdout.write(f"Existing branch ID {old_id}; creating replacement physical consolidated branch")
        if not options["apply"]:
            self.stdout.write("DRY RUN. Supply --apply to execute.")
            return
        # No data should be left after the earlier fresh-start reset.
        from django.db import connection
        with transaction.atomic(using="default"):
            with connection.cursor() as cur:
                cur.execute("""
                    SELECT n.nspname, c.relname, a.attname
                    FROM pg_constraint k
                    JOIN pg_class c ON c.oid=k.conrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    JOIN pg_class target ON target.oid=k.confrelid
                    JOIN pg_namespace tn ON tn.oid=target.relnamespace
                    JOIN LATERAL unnest(k.conkey) AS key(attnum) ON TRUE
                    JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=key.attnum
                    WHERE k.contype='f' AND tn.nspname='public'
                      AND target.relname='branches_branch'
                      AND n.nspname='public'
                      AND c.relname NOT IN ('accounts_user', 'branch_data_branchdatabaseprofile')
                """)
                for schema, table, col in cur.fetchall():
                    cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}" WHERE "{col}"=%s', [old_id])
                    count = cur.fetchone()[0]
                    if count:
                        raise CommandError(f"Cannot replace: {table}.{col} holds {count} old-branch references")
            User.objects.using("default").filter(pk=admin.pk).update(branch_id=None)
            profiles.filter(branch_id=old_id).delete()
            qs.filter(pk=old_id).delete()
            new = qs.create(branch_code="CONSOLIDATED", branch_name="GhazaTech Consolidated", branch_type="PHYSICAL", tax_mode="", is_active=True)
            profiles.create(branch=new, mode="MASTER", database_alias="default", schema_name="", is_master_inventory=True, show_combined_reports=False, is_active=True)
            User.objects.using("default").filter(pk=admin.pk).update(branch_id=new.pk)
            assert qs.count() == profiles.count() == 1
            assert User.objects.using("default").count() == 1
        clear_branch_database_cache()
        self.stdout.write(self.style.SUCCESS(f"Created physical CONSOLIDATED branch ID={new.pk} in default.public"))
