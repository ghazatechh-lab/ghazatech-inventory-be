"""Read-only audit lookup. Run via: python manage.py shell < tools/check_record_actor.py"""
from django.contrib.auth import get_user_model
from apps.audit_logs.models import AuditLog
from apps.branches.models import Branch

branch_id = 2
product_id = 12
collection = '/api/products/'
print(f'Checking product {product_id} in branch {branch_id}:')
print('Audit rows recorded for this exact branch and product:')
logs = (AuditLog.objects.using('default')
        .filter(module__in=['api_record_actor', 'api_last_editor'],
                object_type='api:' + collection,
                object_id=f'{branch_id}:{product_id}')
        .order_by('-created_at'))
for row in logs[:20]:
    user = (get_user_model().objects.using('default').filter(pk=row.user_id).first()
            if row.user_id else None)
    print(row.created_at, row.action, row.user_id,
          (user.full_name or user.username or user.email) if user else 'Unknown')
if not logs.exists():
    print('No matching actor events. Earlier actions cannot be attributed unless a separate record already identifies the actor.')
print('Central actor events recorded (all records):',
      AuditLog.objects.using('default').filter(module='api_record_actor').count())
print('User 1:', list(get_user_model().objects.using('default').filter(pk=1).values('id','username','email','is_superuser')))
