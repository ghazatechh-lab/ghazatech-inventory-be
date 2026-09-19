from celery import shared_task
from django.utils import timezone

from .models import RecoveryRecord, RecoverySettings


@shared_task
def cleanup_expired_recovery_records():
    settings_obj = RecoverySettings.current()
    if not settings_obj.auto_cleanup:
        return {"deleted": 0, "skipped": "auto_cleanup_disabled"}

    deleted = 0
    for record in RecoveryRecord.objects.filter(
        status=RecoveryRecord.STATUS_DELETED,
        expires_at__isnull=False,
        expires_at__lte=timezone.now(),
    ).select_related("content_type"):
        model_class = record.content_type.model_class() if record.content_type else None
        instance = (
            model_class._default_manager.filter(pk=record.object_id).first()
            if model_class
            else None
        )
        if instance is not None:
            try:
                instance.delete()
            except Exception:
                continue
        record.status = RecoveryRecord.STATUS_PERMANENT
        record.permanently_deleted_at = timezone.now()
        record.save(update_fields=["status", "permanently_deleted_at", "updated_at"])
        deleted += 1
    return {"deleted": deleted}
