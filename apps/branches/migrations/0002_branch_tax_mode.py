from django.db import migrations, models


def backfill(apps, schema_editor):
    Branch = apps.get_model("branches", "Branch")
    db = schema_editor.connection.alias
    Branch.objects.using(db).filter(branch_code__iexact="BR01").update(tax_mode="VAT")
    Branch.objects.using(db).filter(branch_code__iexact="BR02").update(tax_mode="NON_VAT")


class Migration(migrations.Migration):
    dependencies = [("branches", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="branch",
            name="tax_mode",
            field=models.CharField(blank=True, choices=[("VAT", "VAT"), ("NON_VAT", "Non-VAT")], default="", max_length=10),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
