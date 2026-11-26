#!/usr/bin/env python3
"""Patch existing shared audit hook to recognize the actual DRF transfer cancel action."""
from pathlib import Path
import argparse
import ast
import shutil
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'apps/audit_logs/viewsets.py'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not TARGET.exists():
        sys.exit(f'Missing {TARGET}; first install the backend actor audit patch.')
    source = TARGET.read_text()
    ast.parse(source, filename=str(TARGET))
    if 'cancel_transfer' in source:
        print('Already supports cancel_transfer; no change needed.')
        return
    if "'cancel', 'confirm'" in source:
        new = source.replace("'cancel', 'confirm'", "'cancel', 'cancel_transfer', 'confirm'", 1)
    elif '"cancel", "confirm"' in source:
        new = source.replace('"cancel", "confirm"', '"cancel", "cancel_transfer", "confirm"', 1)
    else:
        sys.exit('Expected audit action list not found. Aborting without modifications.')
    ast.parse(new, filename=str(TARGET))
    if args.check:
        print('CHECK OK: Audit hook will capture StockTransferViewSet.cancel_transfer.')
        return
    backup = TARGET.with_name(TARGET.name + '.bak-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(TARGET, backup)
    TARGET.write_text(new)
    print(f'Patched: {TARGET}\nBackup: {backup}')


if __name__ == '__main__':
    main()
