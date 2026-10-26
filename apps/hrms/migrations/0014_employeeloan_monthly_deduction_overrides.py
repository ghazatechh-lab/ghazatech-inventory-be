from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("hrms", "0013_alter_employeeletter_letter_type")]
    operations = [
        migrations.AddField(
            model_name="employeeloan",
            name="monthly_deduction_overrides",
            field=models.JSONField(blank=True, default=dict, help_text="Optional YYYY-MM to deduction amount mapping; 0 skips a month."),
        ),
    ]
