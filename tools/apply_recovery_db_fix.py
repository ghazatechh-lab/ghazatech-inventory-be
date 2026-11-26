#!/usr/bin/env python3
"""Safely patch apps/recovery/services.py without replacing the user's whole file."""
from __future__ import annotations

import ast
import argparse
import difflib
from pathlib import Path
import shutil
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check patchability; do not write')
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    target = backend / 'apps' / 'recovery' / 'services.py'
    if not target.is_file():
        print(f'ERROR: Cannot find {target}', file=sys.stderr)
        return 1
    text = target.read_text(encoding='utf-8')
    tree = ast.parse(text, filename=str(target))
    funcs = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'soft_delete_to_recovery']
    if len(funcs) != 1:
        print('ERROR: Expected exactly one soft_delete_to_recovery function. No changes.', file=sys.stderr)
        return 1
    fn = funcs[0]
    saves = [node for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'save' and isinstance(node.func.value, ast.Name) and node.func.value.id == 'instance']
    if len(saves) != 1:
        print('ERROR: Expected exactly one instance.save(...) within soft_delete_to_recovery. No changes.', file=sys.stderr)
        return 1
    save = saves[0]
    if any(kw.arg == 'using' for kw in save.keywords):
        print('Already patched: instance.save already specifies using=.')
        return 0
    if save.args or len(save.keywords) != 1 or save.keywords[0].arg != 'update_fields':
        print('ERROR: Unexpected save signature. No changes.', file=sys.stderr)
        return 1
    # Replace the save call only; preserve all neighboring recovery logic and formatting.
    lines = text.splitlines(keepends=True)
    if save.lineno != save.end_lineno:
        print('ERROR: Multi-line instance.save call needs a manual review. No changes.', file=sys.stderr)
        return 1
    lineno = save.lineno - 1
    current = lines[lineno]
    start, end = save.col_offset, save.end_col_offset
    expected = 'instance.save(update_fields=update_fields)'
    if current[start:end] != expected:
        print('ERROR: Unexpected save call text. No changes.', file=sys.stderr)
        return 1
    replacement = 'instance.save(using=instance._state.db, update_fields=update_fields)'
    lines[lineno] = current[:start] + replacement + current[end:]
    updated = ''.join(lines)
    compile(updated, str(target), 'exec')
    diff = ''.join(difflib.unified_diff(text.splitlines(keepends=True), updated.splitlines(keepends=True), fromfile=str(target), tofile=str(target) + ' (patched)'))
    print(diff)
    if args.check:
        print('Check OK: patch is applicable; no files changed.')
        return 0
    backup = target.with_suffix(target.suffix + '.before_recovery_db_fix.bak')
    if backup.exists():
        print(f'ERROR: Existing backup {backup}. Refusing to overwrite.', file=sys.stderr)
        return 1
    shutil.copy2(target, backup)
    try:
        target.write_text(updated, encoding='utf-8')
        compile(target.read_text(encoding='utf-8'), str(target), 'exec')
    except Exception:
        shutil.copy2(backup, target)
        raise
    print(f'PATCHED: {target}')
    print(f'BACKUP: {backup}')
    print('Next: restart or rebuild the local backend container, then retry the delete request.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
