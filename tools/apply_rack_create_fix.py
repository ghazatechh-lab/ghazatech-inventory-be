#!/usr/bin/env python3
"""Idempotent patch for GhazaTech Inventory rack creation and POST body branch selection.

Run from Inventory root: python3 backend/tools/apply_rack_create_fix.py
No third-party dependencies. Only modifies backend/apps/inventory/{serializers,views}.py.
"""
from __future__ import annotations
import argparse
import ast
import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
SERIALIZER = ROOT / 'backend/apps/inventory/serializers.py'
VIEW = ROOT / 'backend/apps/inventory/views.py'


def find_class(tree, name):
    found = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == name]
    if len(found) != 1:
        raise RuntimeError(f'Expected exactly one class {name}; found {len(found)}')
    return found[0]


def find_method(cls, name):
    found = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(found) != 1:
        raise RuntimeError(f'Expected exactly one {cls.name}.{name}; found {len(found)}')
    return found[0]


def patch_serializer(src):
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    cls = find_class(tree, 'RackSerializer')
    meta = [n for n in cls.body if isinstance(n, ast.ClassDef) and n.name == 'Meta']
    if len(meta) != 1:
        raise RuntimeError('RackSerializer.Meta not found or ambiguous')
    meta = meta[0]
    if not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'model' for t in n.targets) and isinstance(n.value, ast.Name) and n.value.id == 'Rack' for n in meta.body):
        raise RuntimeError('RackSerializer.Meta.model is not Rack; refusing patch')
    edits = []
    branch_fields = [n for n in cls.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and ((isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'branch' for t in n.targets)) or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == 'branch'))]
    field_code = '    branch = serializers.PrimaryKeyRelatedField(read_only=True)\n'
    if not branch_fields:
        # Insert immediately after class declaration, ahead of other fields.
        edits.append((cls.lineno, cls.lineno, field_code))
    elif len(branch_fields) == 1:
        field = branch_fields[0]
        current = ''.join(lines[field.lineno-1:field.end_lineno])
        if current.strip() != field_code.strip():
            edits.append((field.lineno-1, field.end_lineno, field_code))
    else:
        raise RuntimeError('Multiple RackSerializer.branch declarations')
    # Remove only auto-generated cross-DB unique validation, preserving DB constraint.
    validators = [n for n in meta.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'validators' for t in n.targets)]
    if not validators:
        # Place at start of Meta body (before model/fields is fine).
        edits.append((meta.lineno, meta.lineno, '        validators = []  # Validate rack_code in the selected tenant DB\n'))
    elif len(validators) == 1:
        current = ''.join(lines[validators[0].lineno-1:validators[0].end_lineno])
        if 'validators = []' not in current:
            raise RuntimeError('RackSerializer already has custom validators; refusing to overwrite')
    else:
        raise RuntimeError('Multiple Meta.validators declarations')
    for a,b,replacement in sorted(edits, reverse=True):
        lines[a:b] = [replacement]
    out = ''.join(lines)
    ast.parse(out)
    return out


def patch_view(src):
    lines = src.splitlines(keepends=True)
    cls = find_class(ast.parse(src), 'RackViewSet')
    method = find_method(cls, 'perform_create')
    text = ''.join(lines[method.lineno-1:method.end_lineno])
    has_duplicate_check = '_rack_create_tenant_duplicate_check' in text
    if has_duplicate_check and '_rack_post_branch_selection_fix' in text:
        return src
    if 'branch, alias = _inventory_request_scope(self.request, require_physical=True)' not in text:
        raise RuntimeError('RackViewSet.perform_create branch routing differs from expected; refusing patch')
    # Accept explicit selected physical branch on rack creation. The normal
    # request scope is retained when no branch is supplied, and non-superusers
    # must additionally match their authorized request scope.
    if '_rack_post_branch_selection_fix' not in text:
        exact = 'branch, alias = _inventory_request_scope(self.request, require_physical=True)'
        matches = [i for i in range(method.lineno-1, method.end_lineno) if exact in lines[i]]
        if len(matches) != 1:
            raise RuntimeError('Rack create scope assignment differs from expected; refusing patch')
        i_scope = matches[0]
        indent = lines[i_scope][:len(lines[i_scope])-len(lines[i_scope].lstrip())]
        replacement = (
            f'{indent}# _rack_post_branch_selection_fix: respect the rack form branch selection\n'
            f'{indent}selected_branch_id = self.request.data.get("branch")\n'
            f'{indent}if selected_branch_id is None or str(selected_branch_id).strip() == "":\n'
            f'{indent}    branch, alias = _inventory_request_scope(self.request, require_physical=True)\n'
            f'{indent}else:\n'
            f'{indent}    try:\n'
            f'{indent}        if isinstance(selected_branch_id, bool):\n'
            f'{indent}            raise ValueError()\n'
            f'{indent}        selected_branch_pk = int(str(selected_branch_id))\n'
            f'{indent}        if selected_branch_pk <= 0:\n'
            f'{indent}            raise ValueError()\n'
            f'{indent}    except (TypeError, ValueError):\n'
            f'{indent}        raise ValidationError({{"branch": "Select a valid physical branch."}})\n'
            f'{indent}    branch = Branch.objects.using("default").filter(\n'
            f'{indent}        pk=selected_branch_pk, is_active=True, tax_mode__in=("VAT", "NON_VAT")\n'
            f'{indent}    ).first()\n'
            f'{indent}    if branch is None:\n'
            f'{indent}        raise ValidationError({{"branch": "Select an active physical VAT or NON-VAT branch."}})\n'
            f'{indent}    # Prevent cross-branch writes by non-admin users.\n'
            f'{indent}    if not self.request.user.is_superuser:\n'
            f'{indent}        scoped_branch, _ = _inventory_request_scope(self.request, require_physical=True)\n'
            f'{indent}        if scoped_branch.pk != branch.pk:\n'
            f'{indent}            raise ValidationError({{"branch": "Selected branch does not match your authorized branch."}})\n'
            f'{indent}    from apps.branch_data.schema_routing import register_branch_connection\n'
            f'{indent}    alias = register_branch_connection(branch.pk, branch.tax_mode)\n'
        )
        lines[i_scope:i_scope+1] = replacement.splitlines(keepends=True)
        # Recompute the method because this replacement expands the source lines.
        tree = ast.parse(''.join(lines))
        cls = find_class(tree, 'RackViewSet')
        method = find_method(cls, 'perform_create')
        text = ''.join(lines[method.lineno-1:method.end_lineno])
    if 'rack.save(using=alias)' not in text:
        raise RuntimeError('Expected rack.save(using=alias) not found in RackViewSet.perform_create')
    if has_duplicate_check:
        out = ''.join(lines)
        ast.parse(out)
        return out
    # AST confirms exactly one save line in this method.
    save_lines = [i for i in range(method.lineno-1,method.end_lineno) if lines[i].strip() == 'rack.save(using=alias)']
    if len(save_lines) != 1:
        raise RuntimeError(f'Expected one tenant rack save; found {len(save_lines)}')
    i = save_lines[0]
    indent = lines[i][:len(lines[i])-len(lines[i].lstrip())]
    snippet = (
        f'{indent}# _rack_create_tenant_duplicate_check\n'
        f'{indent}if Rack.objects.using(alias).filter(\n'
        f'{indent}    branch_id=branch.pk, rack_code=rack.rack_code\n'
        f'{indent}).exists():\n'
        f'{indent}    raise ValidationError({{"rack_code": "This rack code already exists in the selected branch."}})\n'
    )
    lines.insert(i, snippet)
    out=''.join(lines)
    ast.parse(out)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true', help='Verify safe patch compatibility without changing files')
    args=ap.parse_args()
    try:
        if not SERIALIZER.is_file() or not VIEW.is_file():
            raise RuntimeError(f'Expected backend source files under {ROOT}; verify ZIP extracted at Inventory root')
        originals = {SERIALIZER: SERIALIZER.read_text(), VIEW: VIEW.read_text()}
        updates = {SERIALIZER: patch_serializer(originals[SERIALIZER]), VIEW: patch_view(originals[VIEW])}
        changed = [p for p in updates if originals[p] != updates[p]]
        print('Inventory root:', ROOT)
        for p in updates:
            print(('WOULD UPDATE' if args.check else 'UPDATED' if p in changed else 'ALREADY FIXED') if p in changed else 'ALREADY FIXED', p.relative_to(ROOT))
        if args.check:
            print('Check successful. No files changed.')
            return 0
        if not changed:
            print('Nothing to change (patch already applied).')
            return 0
        timestamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        for p in changed:
            backup=p.with_name(p.name+f'.bak.rackfix-{timestamp}')
            shutil.copy2(p, backup)
            print('Backup:', backup.relative_to(ROOT))
        for p in changed:
            p.write_text(updates[p])
        print('Patch applied. No database records changed. Restart/rebuild backend to load changes.')
        return 0
    except (SyntaxError, RuntimeError, OSError) as exc:
        print('PATCH ABORTED:', exc, file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
