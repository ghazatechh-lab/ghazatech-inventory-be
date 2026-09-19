from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.common.models import TimeStampedModel


class RecoverySettings(TimeStampedModel):
    default_retention_days = models.PositiveIntegerField(default=30)
    finance_retention_days = models.PositiveIntegerField(default=365)
    hrms_retention_days = models.PositiveIntegerField(default=365)
    auto_cleanup = models.BooleanField(default=False)
    require_deletion_reason = models.BooleanField(default=False)
    protect_paid_invoices = models.BooleanField(default=True)
    protect_posted_journals = models.BooleanField(default=True)
    protect_vat_records = models.BooleanField(default=True)
    protect_transactional_products = models.BooleanField(default=True)
    permanent_delete_confirmation = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Recovery setting"
        verbose_name_plural = "Recovery settings"

    @classmethod
    def current(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RecoveryRecord(TimeStampedModel):
    STATUS_DELETED = "DELETED"
    STATUS_RESTORED = "RESTORED"
    STATUS_PERMANENT = "PERMANENTLY_DELETED"
    STATUS_CHOICES = [
        (STATUS_DELETED, "Deleted"),
        (STATUS_RESTORED, "Restored"),
        (STATUS_PERMANENT, "Permanently deleted"),
    ]

    content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recovery_records",
    )
    object_id = models.CharField(max_length=100)
    module = models.CharField(max_length=80)
    model_name = models.CharField(max_length=100)
    record_name = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=150, blank=True)
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recovery_records",
    )
    snapshot = models.JSONField(default=dict, blank=True)
    deletion_reason = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_DELETED,
        db_index=True,
    )
    deleted_at = models.DateTimeField(db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_recovery_records",
    )
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restored_recovery_records",
    )
    permanently_deleted_at = models.DateTimeField(null=True, blank=True)
    permanently_deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="permanently_deleted_recovery_records",
    )

    class Meta:
        ordering = ["-deleted_at", "-id"]
        indexes = [
            models.Index(fields=["status", "module"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return self.reference or self.record_name or f"{self.model_name} #{self.object_id}"
