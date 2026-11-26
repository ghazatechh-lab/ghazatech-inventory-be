#!/usr/bin/env python3
"""Safely repair catalog audit attribution without replacing newer Inventory source."""
from pathlib import Path
import argparse
import ast
import shutil
from datetime import datetime

p = argparse.ArgumentParser()
p.add_argument('--check', action='store_true')
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
target = root / 'backend/apps/inventory/views.py'
if not target.exists():
    target = root / 'apps/inventory/views.py'
if not target.exists():
    raise SystemExit('Cannot find apps/inventory/views.py')
src = target.read_text()
marker = '    def _record_catalog_actor(self, obj, action):'
if marker in src:
    print('Already installed:', target)
    raise SystemExit(0)
cls = 'class TenantCatalogMixin:\n    """Keep catalog reference operations in the selected tenant schema."""\n'
if src.count(cls) != 1:
    raise SystemExit('Unexpected TenantCatalogMixin structure; no changes made')
methods = '''
    def _record_catalog_actor(self, obj, action):
        """Record the actual DRF-authenticated editor after a successful tenant save."""
        import logging
        from apps.audit_logs.models import AuditLog
        actor = getattr(self.request, "user", None)
        if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
            logging.getLogger(__name__).warning(
                "Catalog audit: authenticated actor unavailable for %s %s", action, obj.pk
            )
            return
        branch, alias = _inventory_request_scope(self.request, require_physical=True)
        if obj._state.db != alias:
            raise ValidationError({"branch": "Catalog audit branch does not match the saved tenant."})
        path = "/api/categories/" if isinstance(obj, Category) else "/api/brands/"
        try:
            AuditLog.objects.using("default").create(
                user_id=actor.pk,
                branch_id=branch.pk,
                module="api_record_actor",
                action=action,
                description=f"{action.title()} {path} by user {actor.pk}",
                object_type="api:" + path,
                object_id=f"{branch.pk}:{obj.pk}",
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Catalog audit write FAILED: %s branch=%s id=%s actor=%s",
                path, branch.pk, obj.pk, actor.pk,
            )

    def finalize_response(self, request, response, *args, **kwargs):
        """Include actor labels on catalog responses even if middleware misses them."""
        response = super().finalize_response(request, response, *args, **kwargs)
        if request.method == "GET" and 200 <= response.status_code < 300:
            try:
                from apps.audit_logs.middleware import AuditMiddleware
                AuditMiddleware(lambda unused: response)._annotate(request, response)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Catalog actor response annotation failed")
        return response
'''
src = src.replace(cls, cls + methods, 1)
# Modify only the matching methods, never other inventory views.
a0 = src.index('class TenantCatalogMixin:')
a1 = src.index('\nclass BrandViewSet(', a0)
section = src[a0:a1]
for method, action in (("perform_create", "CREATED"), ("perform_update", "UPDATED")):
    start = section.index("    def " + method + "(")
    end = section.find("\n    def ", start + 5)
    if end == -1:
        end = len(section)
    part = section[start:end]
    needle = "        serializer.instance = obj\n"
    if part.count(needle) != 1:
        raise SystemExit(f'Unexpected {method} method; no changes made')
    part = part.replace(needle, needle + f'        self._record_catalog_actor(obj, "{action}")\n')
    section = section[:start] + part + section[end:]
src = src[:a0] + section + src[a1:]
ast.parse(src)
if a.check:
    print('CHECK OK: can patch', target)
else:
    backup = target.with_name(target.name + '.bak.actor-' + datetime.now().strftime('%Y%m%d%H%M%S'))
    shutil.copy2(target, backup)
    target.write_text(src)
    print('PATCHED:', target)
    print('BACKUP:', backup)
