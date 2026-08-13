from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import create_immutable_audit
from apps.inventory.services import adjust_stock


@transaction.atomic
def confirm_grn(grn, user, request=None):
    # Lock ONLY the GRN table row.
    grn_model = grn.__class__

    grn = grn_model._base_manager.select_for_update(of=("self",)).get(pk=grn.pk)

    if grn.is_confirmed:
        return grn

    # Lock ONLY the Purchase Order row.
    purchase_order_model = grn.purchase_order.__class__

    purchase_order = purchase_order_model._base_manager.select_for_update(
        of=("self",)
    ).get(pk=grn.purchase_order_id)

    # Get the PurchaseOrderItem model without relying on
    # the related manager's default queryset.
    po_item_model = purchase_order.items.model

    for item in grn.items.select_related(
        "product",
        "variant",
    ).all():
        quantity = int(item.accepted_quantity or 0)

        if quantity <= 0:
            quantity = max(
                0,
                int(item.received_quantity or 0)
                - int(item.damaged_quantity or 0)
                - int(
                    getattr(
                        item,
                        "rejected_quantity",
                        0,
                    )
                    or 0
                ),
            )

        if quantity > 0:
            adjust_stock(
                product=item.product,
                variant=item.variant,
                branch=grn.branch,
                warehouse=(grn.warehouse_location or ""),
                quantity=quantity,
                movement_type="PURCHASE",
                performed_by=user,
                reference_type="GRN",
                reference_id=grn.id,
                remarks=(f"PO {purchase_order.po_number}"),
            )

        # IMPORTANT:
        # Use _base_manager + *_id fields.
        #
        # This avoids nullable select_related joins
        # while SELECT FOR UPDATE is active.
        po_item_query = po_item_model._base_manager.select_for_update(
            of=("self",)
        ).filter(
            purchase_order_id=purchase_order.id,
            product_id=item.product_id,
        )

        if item.variant_id:
            po_item_query = po_item_query.filter(
                variant_id=item.variant_id,
            )
        else:
            po_item_query = po_item_query.filter(
                variant_id__isnull=True,
            )

        po_item = po_item_query.first()

        if po_item:
            po_item.received_quantity = min(
                int(po_item.quantity or 0),
                int(po_item.received_quantity or 0) + quantity,
            )

            po_item.save(
                update_fields=[
                    "received_quantity",
                ]
            )

    # Reload PO items directly through the base manager.
    #
    # No SELECT FOR UPDATE is needed here because each row
    # was already locked/updated above inside this transaction.
    po_items = list(
        po_item_model._base_manager.filter(purchase_order_id=purchase_order.id)
    )

    if po_items and all(
        int(po_item.received_quantity or 0) >= int(po_item.quantity or 0)
        for po_item in po_items
    ):
        purchase_order.status = "RECEIVED"

    elif any(int(po_item.received_quantity or 0) > 0 for po_item in po_items):
        purchase_order.status = "PARTIALLY_RECEIVED"

    purchase_order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    grn.is_confirmed = True
    grn.status = "CONFIRMED"
    grn.confirmed_at = timezone.now()

    grn.save(
        update_fields=[
            "is_confirmed",
            "status",
            "confirmed_at",
            "updated_at",
        ]
    )

    create_immutable_audit(
        user=user,
        branch=grn.branch,
        action="GRN_CONFIRMED",
        obj=grn,
        after={
            "status": "CONFIRMED",
            "po": purchase_order.po_number,
        },
        request=request,
    )

    return grn
