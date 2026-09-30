from django.utils import timezone

from apps.branch_data.models import MasterInventorySyncLog
from apps.branch_data.services import database_alias_for_branch, inventory_branch_for


def normalize_inventory_branch(source_branch):
    """All physical stock lives under the configured Master branch."""
    return inventory_branch_for(source_branch)


def create_sync_log(
    *,
    source_branch,
    product,
    variant=None,
    quantity,
    movement_type,
    reference_type="",
    reference_id="",
    source_document_number="",
    status="SUCCESS",
    error_message="",
):
    master_branch = inventory_branch_for(source_branch)
    return MasterInventorySyncLog.objects.using("default").create(
        source_branch=source_branch,
        product=product,
        variant=variant,
        master_branch=master_branch,
        source_database=database_alias_for_branch(source_branch),
        source_document_type=reference_type or "",
        source_document_id=str(reference_id or ""),
        source_document_number=source_document_number or "",
        movement_type=movement_type,
        quantity=int(quantity),
        status=status,
        error_message=error_message,
        processed_at=timezone.now(),
    )
