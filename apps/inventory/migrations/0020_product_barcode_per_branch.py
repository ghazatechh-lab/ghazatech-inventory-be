from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0019_productvariant_racks")]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="barcode",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(
                fields=("branch", "barcode"),
                condition=models.Q(branch__isnull=False, barcode__isnull=False),
                name="unique_product_barcode_per_branch",
            ),
        ),
    ]
