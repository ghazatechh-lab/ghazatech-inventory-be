from django.core.management.base import BaseCommand

from apps.finance.accounting import ensure_core_accounts
from apps.finance.models import ChartOfAccount


class Command(BaseCommand):
    help = "Create the core global Chart of Accounts required by system posting."

    def handle(self, *args, **options):
        created = ensure_core_accounts()
        self.stdout.write(self.style.SUCCESS(
            f"Chart of Accounts ready. Created {len(created)} account(s); "
            f"{ChartOfAccount.objects.filter(branch__isnull=True).count()} global account(s) available."
        ))
