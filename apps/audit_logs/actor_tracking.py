"""Cross-module API actor attribution, stored centrally without tenant migrations.

Audit rows are keyed by API collection, physical source branch and model PK.
They are never used to grant authorization or to alter business stock/history.
"""
import logging
import re

from django.contrib.auth import get_user_model
from .models import AuditLog

log = logging.getLogger(__name__)
_DETAIL = re.compile(r"^(?P<collection>/api/(?:[^/?]+/)+)(?P<pk>\d+)/(?:[^/?]+/)?$")


def to_int(value):
    if isinstance(value, dict):
        value = value.get('id', value.get('pk'))
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def person_name(user):
    if user is None:
        return None
    get_full_name = getattr(user, 'get_full_name', None)
    name = (getattr(user, 'full_name', None) or
            (get_full_name() if callable(get_full_name) else None) or
            getattr(user, 'username', None) or getattr(user, 'email', None))
    return str(name).strip() if name else str(user.pk)


def collection_and_pk(path):
    path = (path or '').split('?', 1)[0]
    match = _DETAIL.match(path)
    if match:
        return match.group('collection'), int(match.group('pk'))
    if path.startswith('/api/') and path.endswith('/'):
        return path, None
    return None, None


def rows_from_data(data):
    value = data
    for _ in range(5):
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
        if not isinstance(value, dict):
            return []
        if isinstance(value.get('results'), list):
            return [r for r in value['results'] if isinstance(r, dict)]
        if isinstance(value.get('data'), (dict, list)):
            value = value['data']
            continue
        if isinstance(value.get('result'), (dict, list)):
            value = value['result']
            continue
        return [value] if to_int(value.get('id')) is not None else []
    return []


def branch_id_for(request, collection, row=None):
    row = row or {}
    key = row.get('resource_key')
    if isinstance(key, str) and re.fullmatch(r'\d+:\d+', key):
        return key.split(':', 1)[0]
    data = {}
    if getattr(request, 'method', '') in ('POST', 'PUT', 'PATCH'):
        try:
            data = request.data
        except Exception:
            data = {}
        if not hasattr(data, 'get'):
            data = {}
    query = getattr(request, 'query_params', {})
    headers = getattr(request, 'headers', {})
    # A master-branch request must never override the physical branch attached to a row.
    names = ('source_branch_id', 'source_branch', 'branch_id', 'branch',
             'from_branch_id', 'from_branch')
    for name in names:
        val = to_int(row.get(name))
        if val is not None:
            return str(val)
    # For inventory the source branch is mandatory to avoid overlapping tenant IDs.
    for val in (query.get('source_branch_id'), query.get('branch'),
                data.get('source_branch_id'), data.get('branch'),
                data.get('from_branch'), headers.get('X-Branch-ID')):
        val = to_int(val)
        if val is not None:
            return str(val)
    return ''


def object_key(request, collection, pk, row=None):
    if pk is None:
        return None
    return f'{branch_id_for(request, collection, row)}:{pk}'


def record_event(request, response, *, action, pk=None, actor=None):
    """Called from DRF's authenticated view after successful standard CRUD writes."""
    actor = actor or getattr(request, 'user', None)
    if not getattr(actor, 'is_authenticated', False) or not getattr(actor, 'pk', None):
        log.warning('Audit event missing authenticated user: %s %s', request.method, request.path)
        return False
    collection, path_pk = collection_and_pk(request.path)
    if not collection or action not in ('CREATED', 'UPDATED'):
        return False
    candidate_rows = rows_from_data(getattr(response, 'data', None))
    row = candidate_rows[0] if candidate_rows else {}
    pk = to_int(pk) or path_pk or to_int(row.get('id'))
    if pk is None:
        log.warning('Audit event missing record ID: %s %s', request.method, request.path)
        return False
    key = object_key(request, collection, pk, row)
    if not key:
        return False
    # Inventory tenant IDs may overlap. Refuse unscoped writes to those collections.
    if collection.startswith(('/api/products/', '/api/racks/', '/api/inventory/')) and key.startswith(':'):
        log.warning('Refusing unscoped tenant audit event for %s id=%s', collection, pk)
        return False
    branch_pk = to_int(key.split(':', 1)[0])
    AuditLog.objects.using('default').create(
        user_id=actor.pk,
        branch_id=branch_pk,
        module='api_record_actor', action=action,
        description=f'{action.title()} through {collection} by user {actor.pk}',
        object_type=('api:' + collection)[:100], object_id=key,
    )
    return True


def annotate_response(request, response):
    """Attach Added By and Updated By without exposing Deleted By outside Recovery."""
    collection, _ = collection_and_pk(request.path)
    if not collection or collection.startswith(('/api/audit-logs/', '/api/recovery/')):
        return
    rows = rows_from_data(getattr(response, 'data', None))
    if not rows or len(rows) > 1000:
        return
    keyed = {}
    user_ids = set()
    for row in rows:
        pk = to_int(row.get('id'))
        if pk is None:
            continue
        key = object_key(request, collection, pk, row)
        keyed[key] = row
        for column in ('created_by', 'added_by', 'updated_by'):
            uid = to_int(row.get(column))
            if uid:
                user_ids.add(uid)
    if not keyed:
        return
    names = {u.pk: person_name(u) for u in
             get_user_model().objects.using('default').filter(pk__in=user_ids)}
    for row in rows:
        for source, target in (('created_by', 'added_by_name'), ('added_by', 'added_by_name'),
                               ('updated_by', 'updated_by_name')):
            val = row.get(source)
            if isinstance(val, dict):
                name = val.get('full_name') or val.get('name') or val.get('username') or val.get('email')
                if name:
                    row.setdefault(target, name)
            elif to_int(val) in names:
                row.setdefault(target, names[to_int(val)])
    # Latest successful event wins, across legacy and new audit writers.
    events = (AuditLog.objects.using('default')
              .filter(module__in=('api_record_actor', 'api_last_editor'),
                      object_type=('api:' + collection)[:100], object_id__in=list(keyed))
              .select_related('user').order_by('-created_at', '-pk'))
    seen = set()
    for event in events:
        if event.action not in ('CREATED', 'UPDATED'):
            continue
        identity = (event.object_id, event.action)
        if identity in seen:
            continue
        seen.add(identity)
        row = keyed[event.object_id]
        prefix = 'added' if event.action == 'CREATED' else 'updated'
        if event.user_id:
            row[prefix + '_by_name'] = person_name(event.user)
            row[prefix + '_by_id'] = event.user_id
            row[prefix + '_by_at'] = event.created_at.isoformat()
