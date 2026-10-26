from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventory", "0020_product_barcode_per_branch")]

    operations = [
        migrations.CreateModel(
            name="RackStockAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("rack", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_allocations", to="inventory.rack")),
                ("stock", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rack_allocations", to="inventory.productstock")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("stock", "rack"), name="unique_stock_rack_allocation")]},
        )
    ]
