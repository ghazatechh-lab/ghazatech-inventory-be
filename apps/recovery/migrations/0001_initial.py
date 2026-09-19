# Generated for Ghazatech Recovery Centre.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("branches", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecoverySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("default_retention_days", models.PositiveIntegerField(default=30)),
                ("finance_retention_days", models.PositiveIntegerField(default=365)),
                ("hrms_retention_days", models.PositiveIntegerField(default=365)),
                ("auto_cleanup", models.BooleanField(default=False)),
                ("require_deletion_reason", models.BooleanField(default=False)),
                ("protect_paid_invoices", models.BooleanField(default=True)),
                ("protect_posted_journals", models.BooleanField(default=True)),
                ("protect_vat_records", models.BooleanField(default=True)),
                ("protect_transactional_products", models.BooleanField(default=True)),
                ("permanent_delete_confirmation", models.BooleanField(default=True)),
            ],
            options={"verbose_name": "Recovery setting", "verbose_name_plural": "Recovery settings"},
        ),
        migrations.CreateModel(
            name="RecoveryRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("object_id", models.CharField(max_length=100)),
                ("module", models.CharField(max_length=80)),
                ("model_name", models.CharField(max_length=100)),
                ("record_name", models.CharField(blank=True, max_length=255)),
                ("reference", models.CharField(blank=True, max_length=150)),
                ("snapshot", models.JSONField(blank=True, default=dict)),
                ("deletion_reason", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("DELETED", "Deleted"), ("RESTORED", "Restored"), ("PERMANENTLY_DELETED", "Permanently deleted")], db_index=True, default="DELETED", max_length=30)),
                ("deleted_at", models.DateTimeField(db_index=True)),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("restored_at", models.DateTimeField(blank=True, null=True)),
                ("permanently_deleted_at", models.DateTimeField(blank=True, null=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recovery_records", to="branches.branch")),
                ("content_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recovery_records", to="contenttypes.contenttype")),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="deleted_recovery_records", to=settings.AUTH_USER_MODEL)),
                ("permanently_deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="permanently_deleted_recovery_records", to=settings.AUTH_USER_MODEL)),
                ("restored_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="restored_recovery_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-deleted_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="recoveryrecord",
            index=models.Index(fields=["status", "module"], name="recovery_re_status_74ed0f_idx"),
        ),
        migrations.AddIndex(
            model_name="recoveryrecord",
            index=models.Index(fields=["content_type", "object_id"], name="recovery_re_content_0c3b32_idx"),
        ),
    ]
