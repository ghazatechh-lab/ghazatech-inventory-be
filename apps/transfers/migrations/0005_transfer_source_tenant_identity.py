from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("transfers", "0004_remove_stocktransferitem_stock_classification")]

    operations = [
        migrations.AddField(model_name="stocktransferitem", name="source_product_id", field=models.PositiveBigIntegerField(null=True, blank=True)),
        migrations.AddField(model_name="stocktransferitem", name="source_variant_id", field=models.PositiveBigIntegerField(null=True, blank=True)),
        migrations.AlterField(model_name="stocktransferitem", name="product", field=models.ForeignKey(to="inventory.product", null=True, blank=True, on_delete=models.PROTECT)),
    ]
