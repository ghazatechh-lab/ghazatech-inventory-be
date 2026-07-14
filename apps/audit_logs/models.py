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
