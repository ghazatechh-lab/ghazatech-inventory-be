from .context import get_active_branch_id
from .services import database_alias_for_branch

TRANSACTION_APPS = {
    "sales",
    "purchases",
    "customers",
    "suppliers",
    "finance",
    "shipments",
}

# Reference applications whose rows are mirrored into VAT / Non-VAT.
REFERENCE_APPS = {
    "auth",
    "contenttypes",
    "accounts",
    "branches",
}

# Some reference schemas are required only because a mirrored model contains
# a database FK to them. Their business data remains authoritative on MASTER.
#
# accounts.User has an FK to hrms.Employee, so PostgreSQL requires the
# hrms_employee table to exist when accounts migrations are applied.
SCHEMA_ONLY_APPS = {
    "hrms",
}

# Only product/catalog reference tables are allowed in secondary databases.
# Physical stock tables must stay on MASTER.
REFERENCE_INVENTORY_MODELS = {
    "brand",
    "category",
    "rack",
    "product",
    "productvariant",
}

MASTER_ONLY_APPS = {
    "branch_data",
    "transfers",
    "reports",
    "audit_logs",
    "notifications",
    "recovery",
    "service_repairs",
    "fleet",
    "sessions",
    "admin",
    "token_blacklist",
}


class BranchTransactionRouter:
    def _instance_branch_id(self, hints):
        instance = hints.get("instance")
        if instance is None:
            return None

        branch_id = getattr(instance, "branch_id", None)
        if branch_id:
            return branch_id

        branch = getattr(instance, "branch", None)
        return getattr(branch, "pk", None)

    def _alias(self, hints):
        branch_id = self._instance_branch_id(hints) or get_active_branch_id()
        return database_alias_for_branch(branch_id) if branch_id else "default"

    def db_for_read(self, model, **hints):
        label = model._meta.app_label

        if label in TRANSACTION_APPS:
            return self._alias(hints)

        # Shared/reference data, HRMS, and physical inventory remain
        # authoritative on MASTER during normal application operation.
        return "default"

    def db_for_write(self, model, **hints):
        label = model._meta.app_label

        if label in TRANSACTION_APPS:
            return self._alias(hints)

        # Reference-data edits, HRMS writes, and inventory writes happen on MASTER.
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        labels = {obj1._meta.app_label, obj2._meta.app_label}

        if labels & (
            TRANSACTION_APPS | REFERENCE_APPS | SCHEMA_ONLY_APPS | {"inventory"}
        ):
            return True

        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "default":
            return True

        if db not in {"vat", "non_vat"}:
            return None

        # Actual transaction tables belong in the selected secondary database.
        if app_label in TRANSACTION_APPS:
            return True

        # Shared reference schemas and rows.
        if app_label in REFERENCE_APPS:
            return True

        # Schema required only to satisfy FK constraints from mirrored models.
        # Reads/writes for these apps are still routed to default.
        if app_label in SCHEMA_ONLY_APPS:
            return True

        if app_label == "inventory":
            return (model_name or "").lower() in REFERENCE_INVENTORY_MODELS

        # Do not silently create unrelated application tables.
        return False
