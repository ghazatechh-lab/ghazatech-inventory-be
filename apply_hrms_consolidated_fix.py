#!/usr/bin/env python3
"""Minimal workforce consolidated-recognition hotfix; makes no DB changes."""
from pathlib import Path
import re
path = Path("apps/branch_data/workforce_flow.py")
source = path.read_text()
pattern = r'def is_combined\(branch\):\n    return bool\(branch and branch\.is_active and not branch\.tax_mode and branch\.branch_type == "MASTER"\)'
replacement = 'def is_combined(branch):\n    # CONSOLIDATED is a virtual workspace even if historical metadata\n    # identifies its branch_type as PHYSICAL.\n    return bool(\n        branch\n        and branch.is_active\n        and not branch.tax_mode\n        and (\n            branch.branch_type == "MASTER"\n            or str(branch.branch_code).upper() in {"CONSOLIDATED", "BR03"}\n        )\n    )'
updated, count = re.subn(pattern, replacement, source)
if count == 1:
    path.write_text(updated)
    print("Updated workforce_flow.is_combined")
elif '"CONSOLIDATED", "BR03"' in source and 'def is_combined(branch):' in source:
    print("Already supports CONSOLIDATED; no change needed")
else:
    raise SystemExit("Unexpected workforce_flow implementation. Stopped; review manually.")
