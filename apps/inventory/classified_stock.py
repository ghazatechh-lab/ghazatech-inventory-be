from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import create_immutable_audit
from .models import ProductStock, StockMovement

CLASSIFICATIONS = {"REGULAR", "RESTRICTED"}


def _balance_fields(classification):
    if classification == "REGULAR":
        return "regular_quantity", "reserved_regular_quantity"
    if classification == "RESTRICTED":
        return "restricted_quantity", "reserved_restricted_quantity"
    raise ValueError("Invalid stock classification.")


@transaction.atomic
def adjust_classified_stock(
    *,
    product,
    variant,
    branch,
    quantity,
    classification,
    movement_type,
    performed_by=None,
    warehouse="",
    reference_type="",
    reference_id="",
    remarks="",
    allow_negative=False,
):
    if classification not in CLASSIFICATIONS:
        raise ValueError("Invalid stock classification.")
    if variant and variant.product_id != product.id:
        raise ValueError("The selected variant does not belong to the product.")
    stock, _ = ProductStock.objects.select_for_update().get_or_create(
        product=product,
        variant=variant,
        branch=branch,
        defaults={"warehouse": warehouse or "", "reorder_level": product.reorder_level},
    )
    balance_field, _ = _balance_fields(classification)
    previous = int(getattr(stock, balance_field) or 0)
    new = previous + int(quantity)
    if new < 0 and not allow_negative:
        raise ValueError(
            f"Insufficient {classification.lower()} stock for {product.sku}."
        )
    setattr(stock, balance_field, new)
    if warehouse:
        stock.warehouse = warehouse
    stock.sync_legacy_balances()
    stock.save(
        update_fields=[
            balance_field,
            "current_stock",
            "reserved_stock",
            "warehouse",
            "last_stock_update",
            "updated_at",
        ]
    )
    movement = StockMovement.objects.create(
        movement_number=f"SM-{timezone.now():%Y%m%d%H%M%S%f}",
        product=product,
        variant=variant,
        branch=branch,
        warehouse=warehouse or stock.warehouse,
        stock_classification=classification,
        movement_type=movement_type,
        quantity=int(quantity),
        previous_stock=previous,
        new_stock=new,
        reference_type=reference_type,
        reference_id=str(reference_id or ""),
        remarks=remarks,
        performed_by=performed_by,
    )
    return movement


@transaction.atomic
def reclassify_stock(reclassification, user):
    if reclassification.status == "APPROVED":
        return reclassification
    if (
        reclassification.source_classification
        == reclassification.destination_classification
    ):
        raise ValueError("Source and destination classifications must differ.")
    adjust_classified_stock(
        product=reclassification.product,
        variant=reclassification.variant,
        branch=reclassification.branch,
        warehouse=reclassification.warehouse,
        quantity=-reclassification.quantity,
        classification=reclassification.source_classification,
        movement_type="RECLASSIFICATION_OUT",
        performed_by=user,
        reference_type="StockReclassification",
        reference_id=reclassification.pk,
        remarks=reclassification.reason,
    )
    adjust_classified_stock(
        product=reclassification.product,
        variant=reclassification.variant,
        branch=reclassification.branch,
        warehouse=reclassification.warehouse,
        quantity=reclassification.quantity,
        classification=reclassification.destination_classification,
        movement_type="RECLASSIFICATION_IN",
        performed_by=user,
        reference_type="StockReclassification",
        reference_id=reclassification.pk,
        remarks=reclassification.reason,
    )
    reclassification.status = "APPROVED"
    reclassification.approved_by = user
    reclassification.approval_date = timezone.now()
    reclassification.save(
        update_fields=["status", "approved_by", "approval_date", "updated_at"]
    )
    create_immutable_audit(
        user=user,
        branch=reclassification.branch,
        action="STOCK_RECLASSIFICATION_APPROVED",
        obj=reclassification,
        before={"status": "PENDING_APPROVAL"},
        after={"status": "APPROVED"},
        reason=reclassification.reason,
    )
    return reclassification
