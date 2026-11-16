from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [('inventory', '0022_brand_image_category_image')]
    operations = [migrations.AddField(model_name='stockadjustment', name='rack_id', field=models.PositiveBigIntegerField(null=True, blank=True, db_index=True))]
