from django.core.management.base import BaseCommand, CommandError

from apps.branches.models import Branch
from apps.branch_data.models import BranchDatabaseProfile
from apps.branch_data.services import clear_branch_database_cache


class Command(BaseCommand):
    help = "Configure BR01=VAT, BR02=NON_VAT, BR03=combined/virtual."

    def handle(self, *args, **options):
        mapping = [
            ("BR01", "VAT", "vat", False, False),
            ("BR02", "NON_VAT", "non_vat", False, False),
            ("BR03", "MASTER", "default", False, True),
        ]
        for code, mode, alias, master, combined in mapping:
            branch = Branch.objects.filter(branch_code=code).first()
            if not branch:
                raise CommandError(f"Branch {code} does not exist.")
            profile, _ = BranchDatabaseProfile.objects.update_or_create(
                branch=branch,
                defaults={
                    "mode": mode,
                    "database_alias": alias,
                    "is_master_inventory": master,
                    "show_combined_reports": combined,
                    "is_active": True,
                },
            )
            self.stdout.write(self.style.SUCCESS(str(profile)))
        clear_branch_database_cache()
