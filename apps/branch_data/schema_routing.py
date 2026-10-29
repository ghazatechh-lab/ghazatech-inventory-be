"""Explicit opt-in per-branch PostgreSQL connection aliases.

Never silently fall back to public tables when a branch schema is not ready.
These connections are aliases to the existing VAT and NON-VAT databases, not
additional PostgreSQL databases. Each alias has a fixed connection search_path.
"""
import re
from copy import deepcopy
from django.conf import settings
from django.db import connections

SCHEMA_PATTERN = re.compile(r"^branch_[0-9]{8}$")


def branch_alias(branch_id, tax_mode):
    tax_mode = str(tax_mode).upper()
    if tax_mode not in {"VAT", "NON_VAT"}:
        raise ValueError("A physical branch must be VAT or NON_VAT")
    branch_id = int(branch_id)
    if branch_id <= 0:
        raise ValueError("Invalid branch id")
    return ("vat" if tax_mode == "VAT" else "non_vat"), f"branch_{branch_id:08d}"


def register_branch_connection(branch_id, tax_mode):
    base, schema = branch_alias(branch_id, tax_mode)
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("Unsafe PostgreSQL schema")
    alias = f"tenant_{base}_{int(branch_id)}"
    if alias in connections.databases:
        return alias
    cfg = deepcopy(settings.DATABASES[base])
    options = dict(cfg.get("OPTIONS") or {})
    if "options" in options:
        raise RuntimeError("Base database already defines libpq options; refusing to overwrite")
    # Search path is set when the connection opens, including pooled reconnects.
    # pg_catalog is implicit and public is intentionally excluded.
    options["options"] = f"-c search_path={schema}"
    cfg["OPTIONS"] = options
    connections.databases[alias] = cfg
    return alias
