from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import create_immutable_audit
from apps.branch_data.services import database_alias_for_branch
from apps.inventory.services import adjust_stock
from apps.inventory.physical_catalog import (
    ensure_product_catalog_in_database,
    resolve_variant_in_physical_database,
)


def confirm_grn(grn, user, request=None):
    using = getattr(getattr(grn, "_state", None), "db", None) or database_alias_for_branch(
        grn.branch_id
    )

    with transaction.atomic(using=using):
        grn = grn.__class__.objects.using(using).select_for_update().get(pk=grn.pk)
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

            po_item = (
                grn.purchase_order.items.using(using)
                .select_for_update()
                .filter(product_id=item.product_id, variant_id=item.variant_id)
                .first()
            )

            if quantity > 0:
                # A GRN may reference a shared catalog product while inventory
                # lives in the physical branch DB. Ensure the product/variant
                # mirror exists before ProductStock/StockMovement are created.
                destination_product = ensure_product_catalog_in_database(
                    item.product,
                    grn.branch,
                    strict_racks=False,
                    reuse_existing_sku=True,
                )
                destination_variant = resolve_variant_in_physical_database(
                    item.variant, destination_product, grn.branch
                )
                unit_cost = po_item.unit_price if po_item else None
                tax_treatment = po_item.tax_treatment if po_item else item.product.tax_treatment
                vat_percentage = po_item.vat_percentage if po_item else item.product.vat_rate
                adjust_stock(
                    product=destination_product,
                    variant=destination_variant,
                    branch=grn.branch,
                    warehouse=grn.warehouse_location or "",
                    quantity=quantity,
                    movement_type="PURCHASE",
                    performed_by=user,
                    reference_type="GRN",
                    reference_id=grn.id,
                    remarks=f"PO {grn.purchase_order.po_number}",
                    unit_cost=unit_cost,
                    vat_treatment=tax_treatment,
                    vat_percentage=vat_percentage,
                    vat_inclusive=False,
                    source_document_number=grn.grn_number,
                )

            if po_item:
                po_item.received_quantity = min(
                    int(po_item.quantity or 0),
                    int(po_item.received_quantity or 0) + quantity,
                )
                po_item.save(using=using, update_fields=["received_quantity"])

        po_items = list(grn.purchase_order.items.using(using).all())
        if po_items and all(
            int(i.received_quantity or 0) >= int(i.quantity or 0) for i in po_items
        ):
            grn.purchase_order.status = "RECEIVED"
        elif any(int(i.received_quantity or 0) > 0 for i in po_items):
            grn.purchase_order.status = "PARTIALLY_RECEIVED"
        grn.purchase_order.save(using=using, update_fields=["status", "updated_at"])

        grn.is_confirmed = True
        grn.status = "CONFIRMED"
        grn.confirmed_at = timezone.now()
        grn.save(
            using=using,
            update_fields=["is_confirmed", "status", "confirmed_at", "updated_at"],
        )

    create_immutable_audit(
        user=user,
        branch=grn.branch,
        action="GRN_CONFIRMED",
        obj=grn,
        after={"status": "CONFIRMED", "po": grn.purchase_order.po_number},
        request=request,
    )
    return grn
