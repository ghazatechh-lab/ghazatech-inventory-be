from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [('transfers', '0005_transfer_source_tenant_identity')]
    operations = [
        migrations.AddField(model_name='stocktransferitem', name='source_rack_id', field=models.PositiveBigIntegerField(null=True, blank=True)),
        migrations.AddField(model_name='stocktransferitem', name='destination_rack_id', field=models.PositiveBigIntegerField(null=True, blank=True)),
    ]
