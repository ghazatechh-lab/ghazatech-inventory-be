from copy import deepcopy

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role
from apps.branches.models import Branch

from apps.branch_data.services import clear_branch_database_cache


CONFIRM_TOKEN = "RESET-GHAZA-LOCAL"
DATABASES = ("default", "vat", "non_vat")


class Command(BaseCommand):
    help = (
        "DEVELOPMENT ONLY: wipe application data from default/VAT/Non-VAT "
        "databases while preserving branch records and admin users."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            help=f"Required destructive-action token: {CONFIRM_TOKEN}",
        )

    def handle(self, *args, **options):
        if options.get("confirm") != CONFIRM_TOKEN:
            raise CommandError(
                "Refusing to reset data. This command is destructive. "
                f"Re-run with --confirm {CONFIRM_TOKEN} only in local/dev."
            )

        branches = self._snapshot_branches()
        roles = self._snapshot_admin_roles()
        admins = self._snapshot_admin_users()

        if not branches:
            raise CommandError("No branches found; refusing to continue.")
        if not admins:
            raise CommandError(
                "No superuser/ADMIN account found; refusing to continue because "
                "the reset would leave the system without an administrator."
            )

        self.stdout.write(
            self.style.WARNING(
                "Resetting ALL application data in default, vat and non_vat."
            )
        )
        self.stdout.write(
            f"Preserving {len(branches)} branch(es) and {len(admins)} admin user(s)."
        )

        # Flush secondary databases first. Their reference rows will be rebuilt
        # from the restored default database at the end.
        for alias in ("vat", "non_vat"):
            self.stdout.write(f"Flushing {alias}...")
            call_command(
                "flush",
                database=alias,
                interactive=False,
                reset_sequences=True,
                verbosity=0,
            )

        self.stdout.write("Flushing default...")
        call_command(
            "flush",
            database="default",
            interactive=False,
            reset_sequences=True,
            verbosity=0,
        )

        self._restore_default(branches=branches, roles=roles, admins=admins)

        # Recreate the three-branch profile using the current architecture.
        call_command("bootstrap_branch_databases", verbosity=0)

        # Mirror the protected references into both transaction databases.
        call_command("sync_branch_reference_data", database="all", verbosity=0)
        clear_branch_database_cache()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Local data reset completed."))
        self.stdout.write(
            "Preserved: branches, admin users, required admin roles, auth/schema metadata."
        )
        self.stdout.write(
            "Removed: catalog, inventory, customers, suppliers, sales, purchases, "
            "finance, HRMS, shipments, transfers and other application data."
        )
        self.stdout.write(
            "BR01=VAT, BR02=NON_VAT, BR03=combined/virtual profiles were recreated."
        )

    def _snapshot_branches(self):
        rows = []
        for branch in Branch.objects.using("default").all().order_by("pk"):
            rows.append(
                {
                    "pk": branch.pk,
                    "branch_code": branch.branch_code,
                    "branch_name": branch.branch_name,
                    "branch_type": branch.branch_type,
                    "address": branch.address,
                    "city": branch.city,
                    "emirate": branch.emirate,
                    "country": branch.country,
                    "phone": branch.phone,
                    "email": branch.email,
                    "manager_id": branch.manager_id,
                    "is_active": branch.is_active,
                    "created_at": branch.created_at,
                    "updated_at": branch.updated_at,
                }
            )
        return rows

    def _snapshot_admin_roles(self):
        User = get_user_model()
        role_ids = set(
            User.objects.using("default")
            .filter(role_id__isnull=False)
            .filter(is_superuser=True)
            .values_list("role_id", flat=True)
        )
        role_ids.update(
            User.objects.using("default")
            .filter(role__code__iexact="ADMIN")
            .values_list("role_id", flat=True)
        )

        return [
            {
                "pk": role.pk,
                "name": role.name,
                "code": role.code,
                "description": role.description,
                "permissions": deepcopy(role.permissions),
                "is_active": role.is_active,
            }
            for role in Role.objects.using("default").filter(pk__in=role_ids)
        ]

    def _snapshot_admin_users(self):
        User = get_user_model()
        admins = (
            User.objects.using("default")
            .filter(is_superuser=True)
            | User.objects.using("default").filter(role__code__iexact="ADMIN")
        )
        admins = admins.distinct().order_by("pk")

        rows = []
        for user in admins:
            rows.append(
                {
                    "pk": user.pk,
                    "password": user.password,
                    "last_login": user.last_login,
                    "is_superuser": user.is_superuser,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "is_staff": user.is_staff,
                    "is_active": user.is_active,
                    "date_joined": user.date_joined,
                    "full_name": user.full_name,
                    "phone_number": user.phone_number,
                    "profile_image": user.profile_image.name if user.profile_image else "",
                    # Employee records are intentionally wiped.
                    "employee_id": None,
                    "role_id": user.role_id,
                    "branch_id": user.branch_id,
                    "permissions": deepcopy(user.permissions),
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                }
            )
        return rows

    @transaction.atomic(using="default")
    def _restore_default(self, *, branches, roles, admins):
        for role in roles:
            Role.objects.using("default").create(**role)

        # Break the Branch.manager -> User circular dependency during restore.
        manager_by_branch = {
            row["pk"]: row.pop("manager_id", None)
            for row in branches
        }
        for branch in branches:
            Branch.objects.using("default").create(manager_id=None, **branch)

        User = get_user_model()
        for admin in admins:
            User.objects.using("default").create(**admin)

        for branch_id, manager_id in manager_by_branch.items():
            if manager_id and any(row["pk"] == manager_id for row in admins):
                Branch.objects.using("default").filter(pk=branch_id).update(
                    manager_id=manager_id
                )
