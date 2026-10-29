from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("branch_data", "0002_rename_branch_data_source__15bc88_idx_branch_data_source__803206_idx_and_more")]

    operations = [
        migrations.AlterField(model_name="branchdatabaseprofile", name="mode", field=models.CharField(max_length=20, choices=[("MASTER", "Combined / Master"), ("VAT", "VAT"), ("NON_VAT", "Non-VAT")])),
        migrations.AlterField(model_name="branchdatabaseprofile", name="database_alias", field=models.CharField(max_length=40)),
        migrations.AddField(model_name="branchdatabaseprofile", name="schema_name", field=models.CharField(max_length=63, blank=True, default="")),
        migrations.AddConstraint(model_name="branchdatabaseprofile", constraint=models.UniqueConstraint(fields=["database_alias", "schema_name"], name="unique_branch_db_schema")),
    ]
