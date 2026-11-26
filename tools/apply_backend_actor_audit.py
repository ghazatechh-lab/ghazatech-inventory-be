#!/usr/bin/env python3
"""Install audit coverage without overwriting Inventory business logic.

Place this ZIP at the Inventory project root; this installer preserves existing
local edits, makes timestamped backups and is safe to re-run.
"""
from pathlib import Path
from datetime import datetime
import argparse
import ast
import re
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / 'backend/apps'
LOGGING = APPS / 'common/logging.py'
if not LOGGING.exists():
    raise SystemExit('Missing backend/apps/common/logging.py: extract to Inventory root first')

# These are business view modules, not the audit package itself.
FILES = [p for p in APPS.rglob('views.py') if 'audit_logs' not in p.parts]
FILES.append(LOGGING)
updates = {}
for path in FILES:
    original = path.read_text()
    source = original
    if path == LOGGING:
        source = source.replace(
            'from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet',
            'from rest_framework.viewsets import ReadOnlyModelViewSet\n'
            'from apps.audit_logs.viewsets import AuditedModelViewSet as ModelViewSet',
        )
    else:
        source = re.sub(
            r'^from rest_framework\.viewsets import ModelViewSet\s*$',
            'from apps.audit_logs.viewsets import AuditedModelViewSet as ModelViewSet',
            source, flags=re.MULTILINE,
        )
        # Handle multiline DRF viewset imports, e.g. inventory/views.py.
        pattern = re.compile(r'from rest_framework\.viewsets import \((.*?)\)', re.DOTALL)
        def convert(m):
            inside = m.group(1)
            if not re.search(r'\bModelViewSet\b', inside):
                return m.group(0)
            reduced = re.sub(r'^\s*ModelViewSet,?\s*\n', '', inside, flags=re.MULTILINE)
            return ((('from rest_framework.viewsets import (' + reduced + ')\n') if reduced.strip() else '')
                    + 'from apps.audit_logs.viewsets import AuditedModelViewSet as ModelViewSet')
        source = pattern.sub(convert, source)
        if 'viewsets.ModelViewSet' in source:
            source = source.replace('viewsets.ModelViewSet', 'AuditedModelViewSet')
            if 'from apps.audit_logs.viewsets import AuditedModelViewSet' not in source:
                source = re.sub(r'^(from __future__ import [^\n]+\n)',
                                r'\1from apps.audit_logs.viewsets import AuditedModelViewSet\n', source, count=1) if 'from __future__ import ' in source else 'from apps.audit_logs.viewsets import AuditedModelViewSet\n' + source
        # Some modules use a direct import alongside other DRF classes.
        source = re.sub(
            r'^from rest_framework\.viewsets import ModelViewSet, (.+)$',
            r'from rest_framework.viewsets import \1\nfrom apps.audit_logs.viewsets import AuditedModelViewSet as ModelViewSet',
            source, flags=re.MULTILINE,
        )
    if source != original:
        ast.parse(source, filename=str(path))
        updates[path] = source

if not updates:
    print('Already installed or no eligible view imports found.')
else:
    print('AUDITABLE VIEW FILES:', len(updates))
    for path in updates:
        print(' -', path.relative_to(ROOT))
    if not args.check:
        suffix = datetime.now().strftime('%Y%m%d%H%M%S')
        for path, source in updates.items():
            backup = path.with_suffix(path.suffix + '.before_actor_audit.' + suffix)
            shutil.copy2(path, backup)
            path.write_text(source)
        print('Applied audit view inheritance; backups made. No database changes.')
if args.check:
    print('CHECK COMPLETE: no files modified')
