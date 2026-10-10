from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.branches.models import Branch
from apps.inventory.models import Product, ProductStock


class Command(BaseCommand):
    help = "Read-only: locate a SKU in shared and physical catalogs, including deleted rows."

    def add_arguments(self, parser):
        parser.add_argument("sku")

    def handle(self, *args, **options):
        sku = options["sku"].strip()
        if not sku:
            raise CommandError("SKU is required.")
        # Include deleted rows because database uniqueness also covers them.
        manager = Product._base_manager
        for alias in ("default", "vat", "non_vat"):
            self.stdout.write(f"\nDatabase: {alias}")
            if alias not in connections:
                self.stdout.write("Not configured")
                continue
            tables = set(connections[alias].introspection.table_names())
            if Product._meta.db_table not in tables:
                self.stdout.write("Product catalog table is not present; skipped")
                continue
            rows = list(manager.using(alias).filter(sku__iexact=sku).values(
                "id", "sku", "product_name", "branch_id", "is_deleted", "is_active"
            ))
            if not rows:
                self.stdout.write("No matching product")
            for row in rows:
                branch = Branch.objects.using("default").filter(pk=row["branch_id"]).first()
                row["branch_code"] = branch.branch_code if branch else None
                # Shared catalog rows do not own stock. Never query the stock
                # table in default; some deployments intentionally omit it.
                if alias == "default":
                    row["stock_rows"] = "Not applicable: stock lives in physical databases"
                elif ProductStock._meta.db_table not in tables:
                    row["stock_rows"] = "Stock table is not present in this physical database"
                else:
                    row["stock_rows"] = list(ProductStock._base_manager.using(alias).filter(
                        product_id=row["id"]
                    ).values("id", "branch_id", "current_stock", "reserved_stock"))
                self.stdout.write(str(row))
        self.stdout.write("\nRead-only check complete. No records changed.")
