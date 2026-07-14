from django.db import models
from apps.common.models import TimeStampedModel


class Notification(TimeStampedModel):
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="notifications"
    )
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.CASCADE
    )
    notification_type = models.CharField(max_length=60)
    title = models.CharField(max_length=250)
    message = models.TextField()
    priority = models.CharField(max_length=20, default="INFO")
    is_read = models.BooleanField(default=False)
    related_model = models.CharField(max_length=100, blank=True)
    related_object_id = models.CharField(max_length=100, blank=True)
