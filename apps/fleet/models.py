from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from apps.common.models import TimeStampedModel


class Vehicle(TimeStampedModel):
    STATUS_CHOICES = [("AVAILABLE", "Available"), ("OUT", "Out"), ("SERVICE", "In Service"), ("INACTIVE", "Inactive")]
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="fleet_vehicles")
    vehicle_code = models.CharField(max_length=40, unique=True)
    make = models.CharField(max_length=80)
    model = models.CharField(max_length=80)
    registration_number = models.CharField(max_length=60, unique=True)
    vehicle_type = models.CharField(max_length=50, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    odometer_km = models.PositiveIntegerField(default=0)
    service_due_km = models.PositiveIntegerField(null=True, blank=True)
    fuel_type = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="AVAILABLE")
    notes = models.TextField(blank=True)
    vehicle_image = models.ImageField(upload_to="fleet/vehicles/images/", null=True, blank=True)

    class Meta:
        ordering = ["make", "model", "registration_number"]

    def __str__(self):
        return f"{self.make} {self.model} - {self.registration_number}"


class VehicleDocument(TimeStampedModel):
    TYPE_CHOICES = [
        ("RC", "Registration Certificate / RC"),
        ("INSURANCE", "Insurance"),
        ("POLLUTION", "Pollution Certificate"),
        ("FITNESS", "Fitness Certificate"),
        ("PERMIT", "Permit"),
        ("TAX", "Tax Document"),
        ("SERVICE", "Service Document"),
        ("WARRANTY", "Warranty"),
        ("LEASE", "Lease Document"),
        ("OTHER", "Other"),
    ]

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default="OTHER")
    title = models.CharField(max_length=150)
    document_number = models.CharField(max_length=100, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    file = models.FileField(
        upload_to="fleet/vehicles/documents/",
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png", "doc", "docx"])],
    )
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="uploaded_vehicle_documents",
    )

    class Meta:
        ordering = ["expiry_date", "-created_at"]

    @property
    def expiry_status(self):
        if not self.expiry_date:
            return "VALID"
        today = timezone.localdate()
        if self.expiry_date < today:
            return "EXPIRED"
        threshold_days = int(getattr(settings, "FLEET_DOCUMENT_EXPIRY_SOON_DAYS", 30))
        if (self.expiry_date - today).days <= threshold_days:
            return "EXPIRING_SOON"
        return "VALID"

    def __str__(self):
        return f"{self.vehicle} - {self.title}"


class VehicleTrip(TimeStampedModel):
    STATUS_CHOICES = [("ACTIVE", "Active"), ("RETURNED", "Returned"), ("CANCELLED", "Cancelled")]
    FUEL_CHOICES = [("FULL", "Full"), ("THREE_QUARTER", "3/4"), ("HALF", "1/2"), ("QUARTER", "1/4"), ("LOW", "Low")]
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="trips")
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="fleet_trips")
    driver = models.ForeignKey("hrms.Employee", on_delete=models.PROTECT, related_name="vehicle_trips")
    checkout_at = models.DateTimeField()
    expected_return_at = models.DateTimeField(null=True, blank=True)
    actual_return_at = models.DateTimeField(null=True, blank=True)
    starting_odometer_km = models.PositiveIntegerField()
    ending_odometer_km = models.PositiveIntegerField(null=True, blank=True)
    fuel_level_out = models.CharField(max_length=20, choices=FUEL_CHOICES, default="FULL")
    fuel_level_return = models.CharField(max_length=20, choices=FUEL_CHOICES, blank=True)
    destination = models.CharField(max_length=255, blank=True)
    purpose = models.CharField(max_length=255)
    departure_notes = models.TextField(blank=True)
    return_notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_vehicle_trips")
    parking_location = models.CharField(max_length=150, blank=True)
    expense_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    receipt = models.FileField(upload_to="fleet/receipts/", null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")

    class Meta:
        ordering = ["-checkout_at"]

    @property
    def distance_km(self):
        if self.ending_odometer_km is None:
            return None
        return max(0, self.ending_odometer_km - self.starting_odometer_km)
