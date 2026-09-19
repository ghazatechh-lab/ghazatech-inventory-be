import json
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.audit_logs.models import AuditLog

from .models import RecoveryRecord, RecoverySettings


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, default=str))


def _reference_for(instance):
    for field in (
        "invoice_number",
        "invoice_no",
        "order_number",
        "po_number",
        "customer_code",
        "supplier_code",
        "sku",
        "employee_code",
        "code",
        "reference",
    ):
        value = getattr(instance, field, None)
        if value not in (None, ""):
            return str(value)
    return f"{instance._meta.verbose_name.title()}-{instance.pk}"


def _record_name_for(instance):
    for field in (
        "product_name",
        "customer_name",
        "supplier_name",
        "full_name",
        "name",
        "title",
    ):
        value = getattr(instance, field, None)
        if value not in (None, ""):
            return str(value)
    return str(instance)


def retention_days_for(instance):
    settings_obj = RecoverySettings.current()
    app_label = instance._meta.app_label.lower()
    if app_label == "finance":
        return settings_obj.finance_retention_days
    if app_label == "hrms":
        return settings_obj.hrms_retention_days
    return settings_obj.default_retention_days


def create_recovery_record(instance, user=None, reason="", request=None):
    now = timezone.now()
    reason = (reason or "").strip() or "Deleted from ERP"
    content_type = ContentType.objects.get_for_model(instance, for_concrete_model=False)
    branch = getattr(instance, "branch", None)
    snapshot = _json_safe(model_to_dict(instance))
    retention_days = retention_days_for(instance)

    record, _ = RecoveryRecord.objects.update_or_create(
        content_type=content_type,
        object_id=str(instance.pk),
        status=RecoveryRecord.STATUS_DELETED,
        defaults={
            "module": instance._meta.app_label,
            "model_name": instance._meta.model_name,
            "record_name": _record_name_for(instance),
            "reference": _reference_for(instance),
            "branch": branch,
            "snapshot": snapshot,
            "deletion_reason": reason,
            "deleted_at": now,
            "deleted_by": user if getattr(user, "is_authenticated", False) else None,
            "expires_at": now + timedelta(days=retention_days),
        },
    )

    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        branch=branch,
        module="recovery",
        action="delete",
        description=f"{record.reference or record.record_name} moved to Recovery Centre.",
        object_type=f"{instance._meta.app_label}.{instance._meta.model_name}",
        object_id=str(instance.pk),
        reason=reason,
        before_values=snapshot,
    )
    return record


def soft_delete_to_recovery(instance, user=None, reason="", request=None):
    if not hasattr(instance, "is_deleted"):
        raise ValueError("Model does not support soft deletion.")

    record = create_recovery_record(
        instance=instance,
        user=user,
        reason=reason,
        request=request,
    )

    instance.is_deleted = True
    if hasattr(instance, "deleted_at"):
        instance.deleted_at = timezone.now()
    if hasattr(instance, "deleted_by"):
        instance.deleted_by = user if getattr(user, "is_authenticated", False) else None

    update_fields = ["is_deleted"]
    if hasattr(instance, "deleted_at"):
        update_fields.append("deleted_at")
    if hasattr(instance, "deleted_by"):
        update_fields.append("deleted_by")
    if hasattr(instance, "updated_at"):
        update_fields.append("updated_at")
    instance.save(update_fields=update_fields)
    return record
