from apps.branch_data.services import database_alias_for_branch

PHYSICAL_CODES = {"BR01", "BR02"}
TRANSACTION_APPS = {"sales", "purchases", "customers", "suppliers", "finance", "shipments"}
PHYSICAL_INVENTORY_MODELS = {"productstock", "stockmovement", "stockadjustment"}


def source_database_for_record(record):
    snapshot = record.snapshot or {}
    explicit = snapshot.get("__recovery_source_db")
    if explicit in {"default", "vat", "non_vat"}:
        return explicit
    if not record.branch_id:
        return "default"
    if record.module in TRANSACTION_APPS or (
        record.module == "inventory" and record.model_name in PHYSICAL_INVENTORY_MODELS
    ):
        return database_alias_for_branch(record.branch_id)
    return "default"
