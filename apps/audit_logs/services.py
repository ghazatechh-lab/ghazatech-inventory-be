from .models import AuditLog


def log_action(user, branch, module, action, description, obj=None, ip=None):
    return AuditLog.objects.create(
        user=user,
        branch=branch,
        module=module,
        action=action,
        description=description,
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(obj.pk) if obj else "",
        ip_address=ip,
    )
