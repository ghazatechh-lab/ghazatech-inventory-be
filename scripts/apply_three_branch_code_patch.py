#!/usr/bin/env python3

from pathlib import Path
import re

ROOT = Path.cwd()


def patch_file(path, transform):
    p = ROOT / path

    if not p.exists():
        print(f"SKIP missing: {path}")
        return

    before = p.read_text(encoding="utf-8")
    after = transform(before)

    if after == before:
        print(f"UNCHANGED: {path}")
        return

    backup = p.with_suffix(p.suffix + ".pre_three_branch")

    if not backup.exists():
        backup.write_text(before, encoding="utf-8")

    p.write_text(after, encoding="utf-8")
    print(f"UPDATED: {path}")


# ---------------------------------------------------------
# SALES MODELS
# ---------------------------------------------------------

def patch_sales_models(text):
    # Already patched
    if (
        "SALE_MODE_CHOICES" in text
        and re.search(
            r"^\s+sale_mode\s*=\s*models\.CharField",
            text,
            flags=re.MULTILINE,
        )
    ):
        return text

    # Add shared choices after imports and before first class.
    if "SALE_MODE_CHOICES" not in text:
        first_class = re.search(r"^class\s+", text, flags=re.MULTILINE)

        if not first_class:
            raise RuntimeError(
                "Could not locate first class in apps/sales/models.py"
            )

        choices = """
SALE_MODE_CHOICES = [
    ("VAT", "VAT Sale"),
    ("NON_VAT", "Non-VAT Sale"),
]


"""
        text = (
            text[: first_class.start()]
            + choices
            + text[first_class.start() :]
        )

    # Find DocumentBase.
    match = re.search(
        r"^class\s+DocumentBase\s*\([^)]*\)\s*:",
        text,
        flags=re.MULTILINE,
    )

    if not match:
        raise RuntimeError(
            "Could not locate DocumentBase in apps/sales/models.py"
        )

    # Find its Meta class.
    next_meta = re.search(
        r"^\s{4}class\s+Meta\s*:",
        text[match.end() :],
        flags=re.MULTILINE,
    )

    if not next_meta:
        raise RuntimeError(
            "Could not locate DocumentBase.Meta"
        )

    insert_at = match.end() + next_meta.start()

    sale_mode_field = """

    sale_mode = models.CharField(
        max_length=20,
        choices=SALE_MODE_CHOICES,
        default="VAT",
    )

"""

    text = (
        text[:insert_at]
        + sale_mode_field
        + text[insert_at:]
    )

    return text


# ---------------------------------------------------------
# DATABASE MIXIN -> BRANCH FILTER MIXIN
# ---------------------------------------------------------

def replace_db_mixin(text):
    text = text.replace(
        "from apps.branch_data.mixins import BranchDatabaseQuerysetMixin",
        "from apps.common.three_branch import BranchAccessQuerysetMixin",
    )

    text = text.replace(
        "BranchDatabaseQuerysetMixin",
        "BranchAccessQuerysetMixin",
    )

    return text


# ---------------------------------------------------------
# SALES VIEWS
# ---------------------------------------------------------

def patch_sales_views(text):
    text = replace_db_mixin(text)

    # Add guard import if missing.
    if "SalesBranchGuardMixin" not in text:
        import_line = (
            "from apps.common.three_branch import "
            "SalesBranchGuardMixin, "
            "get_requested_branch, "
            "request_sale_mode\n"
        )

        lines = text.splitlines(True)

        insert_index = 0

        for i, line in enumerate(lines):
            if line.startswith("from ") or line.startswith("import "):
                insert_index = i + 1
            elif insert_index:
                break

        lines.insert(insert_index, import_line)
        text = "".join(lines)

    # Remove duplicate single import created by previous replacement.
    text = text.replace(
        "from apps.common.three_branch import BranchAccessQuerysetMixin\n",
        "",
    )

    # Change Base inheritance.
    text = re.sub(
        r"^class\s+Base\s*\([^)]*ModelViewSet[^)]*\)\s*:",
        "class Base(SalesBranchGuardMixin, ModelViewSet):",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # Some versions use simply class Base(ModelViewSet)
    text = re.sub(
        r"^class\s+Base\s*\(\s*ModelViewSet\s*\)\s*:",
        "class Base(SalesBranchGuardMixin, ModelViewSet):",
        text,
        count=1,
        flags=re.MULTILINE,
    )

    return text


# ---------------------------------------------------------
# BRANCH SELECTOR
# ---------------------------------------------------------

def patch_branch_views(text):
    if "branch_sales_mode" not in text:
        lines = text.splitlines(True)

        insert_index = 0

        for i, line in enumerate(lines):
            if line.startswith("from ") or line.startswith("import "):
                insert_index = i + 1
            elif insert_index:
                break

        lines.insert(
            insert_index,
            "from apps.common.three_branch import "
            "branch_sales_mode, allowed_sale_modes\n",
        )

        text = "".join(lines)

    # Add metadata anywhere branch selector serializes branch_code/name.
    pattern = re.compile(
        r'("branch_code"\s*:\s*branch\.branch_code\s*,\s*'
        r'"branch_name"\s*:\s*branch\.branch_name\s*,?)',
        flags=re.MULTILINE,
    )

    def repl(match):
        original = match.group(1)

        if "allowed_sale_modes" in original:
            return original

        if not original.rstrip().endswith(","):
            original = original.rstrip() + ","

        return (
            original
            + '\n                        '
            + '"sales_mode": branch_sales_mode(branch),'
            + '\n                        '
            + '"allowed_sale_modes": allowed_sale_modes(branch),'
        )

    text = pattern.sub(repl, text)

    return text


# ---------------------------------------------------------
# APPLY
# ---------------------------------------------------------

patch_file(
    "apps/sales/models.py",
    patch_sales_models,
)

patch_file(
    "apps/sales/views.py",
    patch_sales_views,
)

for path in [
    "apps/purchases/views.py",
    "apps/finance/views.py",
    "apps/customers/views.py",
    "apps/suppliers/views.py",
    "apps/shipments/views.py",
]:
    patch_file(
        path,
        replace_db_mixin,
    )

patch_file(
    "apps/branches/views.py",
    patch_branch_views,
)

print()
print("Three-branch code patch completed.")
print()
print("IMPORTANT:")
print("Do not remove VAT/non-VAT databases yet.")
print("Run Django checks before migrations.")
