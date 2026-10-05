from django.db import migrations, models


SALE_MODE_CHOICES = [
    ("VAT", "VAT Sale"),
    ("NON_VAT", "Non-VAT Sale"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0015_possale_updated_by_quotation_updated_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotation",
            name="sale_mode",
            field=models.CharField(
                choices=SALE_MODE_CHOICES,
                default="VAT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="sale_mode",
            field=models.CharField(
                choices=SALE_MODE_CHOICES,
                default="VAT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="salesinvoice",
            name="sale_mode",
            field=models.CharField(
                choices=SALE_MODE_CHOICES,
                default="VAT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="possale",
            name="sale_mode",
            field=models.CharField(
                choices=SALE_MODE_CHOICES,
                default="VAT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="salesreturn",
            name="sale_mode",
            field=models.CharField(
                choices=SALE_MODE_CHOICES,
                default="VAT",
                max_length=20,
            ),
        ),
    ]
