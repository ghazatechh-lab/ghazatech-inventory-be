from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="vehicle_image",
            field=models.ImageField(blank=True, null=True, upload_to="fleet/vehicles/images/"),
        ),
        migrations.CreateModel(
            name="VehicleDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("document_type", models.CharField(choices=[("RC", "Registration Certificate / RC"), ("INSURANCE", "Insurance"), ("POLLUTION", "Pollution Certificate"), ("FITNESS", "Fitness Certificate"), ("PERMIT", "Permit"), ("TAX", "Tax Document"), ("SERVICE", "Service Document"), ("WARRANTY", "Warranty"), ("LEASE", "Lease Document"), ("OTHER", "Other")], default="OTHER", max_length=30)),
                ("title", models.CharField(max_length=150)),
                ("document_number", models.CharField(blank=True, max_length=100)),
                ("issue_date", models.DateField(blank=True, null=True)),
                ("expiry_date", models.DateField(blank=True, null=True)),
                ("file", models.FileField(upload_to="fleet/vehicles/documents/", validators=[django.core.validators.FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png", "doc", "docx"])])),
                ("notes", models.TextField(blank=True)),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="uploaded_vehicle_documents", to=settings.AUTH_USER_MODEL)),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="fleet.vehicle")),
            ],
            options={"ordering": ["expiry_date", "-created_at"]},
        ),
    ]
