"""Read-only check after a create/edit in UI.
Run from backend: docker compose exec -T backend python manage.py shell < tools/check_actor_audit.py
"""
from apps.audit_logs.models import AuditLog

qs = (AuditLog.objects.using('default')
      .filter(module__in=('api_record_actor', 'api_last_editor'), action__in=('CREATED', 'UPDATED'))
      .select_related('user').order_by('-created_at', '-pk')[:30])
print('Recent API actor events (latest first):')
for item in qs:
    user = item.user
    name = (getattr(user, 'full_name', '') or getattr(user, 'username', '') or
            getattr(user, 'email', '')) if user else '(missing user)'
    print(item.created_at, item.action, item.object_type, item.object_id,
          'user_id=', item.user_id, 'name=', name)
