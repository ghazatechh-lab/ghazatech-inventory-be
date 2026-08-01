from django.db import models
from apps.common.models import TimeStampedModel


class AuditLog(TimeStampedModel):
    user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.SET_NULL
    )
    module = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    description = models.TextField()
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    role = models.CharField(max_length=80, blank=True, default="")
    before_values = models.JSONField(default=dict, blank=True)
    after_values = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    approval_reference = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        permissions = [("view_complete_records", "Can view complete audit records")]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit logs are immutable and cannot be deleted.")
