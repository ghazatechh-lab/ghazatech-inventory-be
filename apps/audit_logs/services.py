from .models import AuditLog


def create_immutable_audit(
    *,
    user,
    action,
    obj=None,
    branch=None,
    before=None,
    after=None,
    reason="",
    approval_reference="",
    request=None,
    description=""
):
    role = getattr(getattr(user, "role", None), "code", "") if user else ""
    ip = None
    if request:
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[
            0
        ].strip() or request.META.get("REMOTE_ADDR")
    return AuditLog.objects.create(
        user=user,
        role=role,
        branch=branch,
        module=getattr(obj, "_meta", None).app_label if obj else "system",
        action=action,
        description=description or action.replace("_", " ").title(),
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(getattr(obj, "pk", "") or ""),
        before_values=before or {},
        after_values=after or {},
        reason=reason,
        approval_reference=approval_reference,
        ip_address=ip,
    )
