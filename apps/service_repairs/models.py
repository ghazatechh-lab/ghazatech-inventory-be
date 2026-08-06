from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class ServiceJob(TimeStampedModel):
    STATUS_RECEIVED = "RECEIVED"
    STATUS_DIAGNOSING = "DIAGNOSING"
    STATUS_AWAITING_APPROVAL = "AWAITING_APPROVAL"
    STATUS_REPAIRING = "REPAIRING"
    STATUS_READY = "READY"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_DELIVERED = "DELIVERED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_DIAGNOSING, "Diagnosing"),
        (STATUS_AWAITING_APPROVAL, "Awaiting Approval"),
        (STATUS_REPAIRING, "Repairing"),
        (STATUS_READY, "Ready for Delivery"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PRIORITY_CHOICES = [
        ("LOW", "Low"),
        ("NORMAL", "Normal"),
        ("HIGH", "High"),
        ("URGENT", "Urgent"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("UNPAID", "Unpaid"),
        ("PARTIAL", "Partially Paid"),
        ("PAID", "Paid"),
    ]

    job_number = models.CharField(max_length=40, unique=True, blank=True)
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="service_jobs",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_jobs",
    )
    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)

    device_type = models.CharField(max_length=60, default="Laptop")
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=150)
    serial_number = models.CharField(max_length=150, blank=True)
    password_or_pin = models.CharField(max_length=150, blank=True)
    accessories_received = models.TextField(blank=True)
    device_condition = models.TextField(blank=True)

    complaint = models.TextField()
    diagnosis = models.TextField(blank=True)
    technician_notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    technician = models.ForeignKey(
        "hrms.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_jobs",
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="NORMAL",
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
    )
    expected_completion_date = models.DateField(null=True, blank=True)
    approval_notes = models.TextField(blank=True)
    customer_approved = models.BooleanField(default=False)

    labour_charge = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default="UNPAID",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_service_jobs",
    )
    updated_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_service_jobs",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["job_number"]),
            models.Index(fields=["serial_number"]),
        ]

    def __str__(self):
        return f"{self.job_number} - {self.customer_name}"

    @property
    def parts_total(self):
        return sum((item.line_total for item in self.charges.all()), Decimal("0.00"))

    @property
    def grand_total(self):
        return max(
            Decimal("0.00"),
            self.parts_total + self.labour_charge + self.tax_amount - self.discount_amount,
        )

    @property
    def balance_due(self):
        return max(Decimal("0.00"), self.grand_total - self.amount_paid)

    def save(self, *args, **kwargs):
        if not self.job_number:
            prefix = timezone.localdate().strftime("SRV-%Y%m")
            latest = (
                ServiceJob.objects.filter(job_number__startswith=prefix)
                .order_by("-id")
                .values_list("job_number", flat=True)
                .first()
            )
            sequence = 1
            if latest:
                try:
                    sequence = int(latest.rsplit("-", 1)[-1]) + 1
                except (TypeError, ValueError):
                    sequence = ServiceJob.objects.filter(
                        job_number__startswith=prefix
                    ).count() + 1
            self.job_number = f"{prefix}-{sequence:04d}"

        now = timezone.now()
        if self.status in {self.STATUS_COMPLETED, self.STATUS_DELIVERED} and not self.completed_at:
            self.completed_at = now
        if self.status == self.STATUS_DELIVERED and not self.delivered_at:
            self.delivered_at = now

        super().save(*args, **kwargs)


class ServiceCharge(TimeStampedModel):
    TYPE_CHOICES = [
        ("PART", "Part"),
        ("SERVICE", "Service"),
        ("OTHER", "Other"),
    ]

    service_job = models.ForeignKey(
        ServiceJob,
        on_delete=models.CASCADE,
        related_name="charges",
    )
    charge_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="PART")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.service_job.job_number}: {self.description}"
