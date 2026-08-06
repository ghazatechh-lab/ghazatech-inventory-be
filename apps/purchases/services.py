from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import create_immutable_audit
from apps.inventory.services import adjust_stock


@transaction.atomic
def confirm_grn(grn, user, request=None):
    grn = grn.__class__.objects.select_for_update().get(pk=grn.pk)
    if grn.is_confirmed:
        return grn

    for item in grn.items.select_related("product", "variant").all():
        quantity = int(item.accepted_quantity or 0)
        if quantity <= 0:
            quantity = max(
                0,
                int(item.received_quantity or 0)
                - int(item.damaged_quantity or 0)
                - int(item.rejected_quantity or 0),
            )

        if quantity > 0:
            adjust_stock(
                product=item.product,
                variant=item.variant,
                branch=grn.branch,
                warehouse=grn.warehouse_location or "",
                quantity=quantity,
                movement_type="PURCHASE",
                performed_by=user,
                reference_type="GRN",
                reference_id=grn.id,
                remarks=f"PO {grn.purchase_order.po_number}",
            )

        po_item = (
            grn.purchase_order.items.select_for_update()
            .filter(product=item.product, variant=item.variant)
            .first()
        )
        if po_item:
            po_item.received_quantity = min(
                int(po_item.quantity or 0),
                int(po_item.received_quantity or 0) + quantity,
            )
            po_item.save(update_fields=["received_quantity"])

    po_items = list(grn.purchase_order.items.all())
    if po_items and all(
        int(i.received_quantity or 0) >= int(i.quantity or 0) for i in po_items
    ):
        grn.purchase_order.status = "RECEIVED"
    elif any(int(i.received_quantity or 0) > 0 for i in po_items):
        grn.purchase_order.status = "PARTIALLY_RECEIVED"
    grn.purchase_order.save(update_fields=["status", "updated_at"])

    grn.is_confirmed = True
    grn.status = "CONFIRMED"
    grn.confirmed_at = timezone.now()
    grn.save(update_fields=["is_confirmed", "status", "confirmed_at", "updated_at"])

    create_immutable_audit(
        user=user,
        branch=grn.branch,
        action="GRN_CONFIRMED",
        obj=grn,
        after={"status": "CONFIRMED", "po": grn.purchase_order.po_number},
        request=request,
    )
    return grn
