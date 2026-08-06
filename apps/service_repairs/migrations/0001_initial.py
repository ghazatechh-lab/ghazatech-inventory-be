# Generated for the Ghazatech Service & Repair module.
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0003_alter_role_options_role_is_active"),
        ("branches", "0001_initial"),
        ("customers", "0002_alter_customer_options_customer_billing_address_and_more"),
        ("hrms", "0008_salaryadvance_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("job_number", models.CharField(blank=True, max_length=40, unique=True)),
                ("customer_name", models.CharField(max_length=150)),
                ("phone", models.CharField(max_length=40)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("device_type", models.CharField(default="Laptop", max_length=60)),
                ("brand", models.CharField(max_length=100)),
                ("model", models.CharField(max_length=150)),
                ("serial_number", models.CharField(blank=True, max_length=150)),
                ("password_or_pin", models.CharField(blank=True, max_length=150)),
                ("accessories_received", models.TextField(blank=True)),
                ("device_condition", models.TextField(blank=True)),
                ("complaint", models.TextField()),
                ("diagnosis", models.TextField(blank=True)),
                ("technician_notes", models.TextField(blank=True)),
                ("internal_notes", models.TextField(blank=True)),
                ("priority", models.CharField(choices=[("LOW", "Low"), ("NORMAL", "Normal"), ("HIGH", "High"), ("URGENT", "Urgent")], default="NORMAL", max_length=20)),
                ("status", models.CharField(choices=[("RECEIVED", "Received"), ("DIAGNOSING", "Diagnosing"), ("AWAITING_APPROVAL", "Awaiting Approval"), ("REPAIRING", "Repairing"), ("READY", "Ready for Delivery"), ("COMPLETED", "Completed"), ("DELIVERED", "Delivered"), ("CANCELLED", "Cancelled")], default="RECEIVED", max_length=30)),
                ("expected_completion_date", models.DateField(blank=True, null=True)),
                ("approval_notes", models.TextField(blank=True)),
                ("customer_approved", models.BooleanField(default=False)),
                ("labour_charge", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("discount_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("tax_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("amount_paid", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("payment_status", models.CharField(choices=[("UNPAID", "Unpaid"), ("PARTIAL", "Partially Paid"), ("PAID", "Paid")], default="UNPAID", max_length=20)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="service_jobs", to="branches.branch")),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="service_jobs", to="customers.customer")),
                ("technician", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="service_jobs", to="hrms.employee")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_service_jobs", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_service_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="ServiceCharge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("charge_type", models.CharField(choices=[("PART", "Part"), ("SERVICE", "Service"), ("OTHER", "Other")], default="PART", max_length=20)),
                ("description", models.CharField(max_length=255)),
                ("quantity", models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=10)),
                ("unit_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("service_job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="charges", to="service_repairs.servicejob")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddIndex(
            model_name="servicejob",
            index=models.Index(fields=["branch", "status"], name="service_repa_branch__79c5dd_idx"),
        ),
        migrations.AddIndex(
            model_name="servicejob",
            index=models.Index(fields=["job_number"], name="service_repa_job_num_6cc7f6_idx"),
        ),
        migrations.AddIndex(
            model_name="servicejob",
            index=models.Index(fields=["serial_number"], name="service_repa_serial__606f88_idx"),
        ),
    ]
