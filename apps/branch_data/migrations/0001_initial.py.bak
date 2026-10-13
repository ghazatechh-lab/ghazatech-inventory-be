from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("branches", "0001_initial"),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BranchDatabaseProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("MASTER", "Combined / Master"), ("VAT", "VAT"), ("NON_VAT", "Non-VAT")], max_length=20, unique=True)),
                ("database_alias", models.CharField(max_length=40, unique=True)),
                ("is_master_inventory", models.BooleanField(default=False)),
                ("show_combined_reports", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="database_profile", to="branches.branch")),
            ],
            options={"ordering": ["branch_id"]},
        ),
        migrations.CreateModel(
            name="MasterInventorySyncLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_database", models.CharField(max_length=40)),
                ("source_document_type", models.CharField(blank=True, max_length=80)),
                ("source_document_id", models.CharField(blank=True, max_length=80)),
                ("source_document_number", models.CharField(blank=True, max_length=120)),
                ("movement_type", models.CharField(max_length=40)),
                ("quantity", models.IntegerField()),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("SUCCESS", "Success"), ("FAILED", "Failed")], default="PENDING", max_length=20)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("master_branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="master_inventory_received_sync_logs", to="branches.branch")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="master_inventory_sync_logs", to="inventory.product")),
                ("source_branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="master_inventory_sync_logs", to="branches.branch")),
                ("variant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="master_inventory_sync_logs", to="inventory.productvariant")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="masterinventorysynclog",
            index=models.Index(fields=["source_branch", "status"], name="branch_data_source__15bc88_idx"),
        ),
        migrations.AddIndex(
            model_name="masterinventorysynclog",
            index=models.Index(fields=["product", "created_at"], name="branch_data_product_272fcf_idx"),
        ),
        migrations.AddIndex(
            model_name="masterinventorysynclog",
            index=models.Index(fields=["source_document_type", "source_document_id"], name="branch_data_source__6bb734_idx"),
        ),
    ]
