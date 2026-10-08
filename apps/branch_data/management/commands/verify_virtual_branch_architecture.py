from django.core.management.base import BaseCommand

from apps.branches.models import Branch
from apps.inventory.models import ProductStock

from apps.branch_data.routing import (
    VAT,
    NON_VAT,
    database_for_source,
)


class Command(BaseCommand):
    help = "Verify BR01/BR02 DB aliases and ensure BR03 owns no ProductStock."

    def handle(self, *args, **options):
        branches = {
            b.branch_code: b
            for b in Branch.objects.filter(
                branch_code__in=["BR01", "BR02", "BR03"]
            )
        }

        for code in ["BR01", "BR02", "BR03"]:
            if code not in branches:
                self.stdout.write(self.style.ERROR(f"Missing {code}"))
                return

        self.stdout.write(f"VAT database alias: {database_for_source(VAT)}")
        self.stdout.write(
            f"NON_VAT database alias: {database_for_source(NON_VAT)}"
        )

        br03_stock = ProductStock.objects.filter(
            branch=branches["BR03"]
        ).count()

        if br03_stock:
            self.stdout.write(
                self.style.ERROR(
                    f"BR03 still owns {br03_stock} ProductStock row(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("BR03 owns no ProductStock rows.")
            )

        self.stdout.write(
            self.style.SUCCESS(
                "BR03 must use explicit combined-query services for reads and "
                "target_branch for writes."
            )
        )
