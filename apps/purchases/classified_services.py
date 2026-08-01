from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import create_immutable_audit
from apps.inventory.classified_stock import adjust_classified_stock


@transaction.atomic
def confirm_classified_grn(grn, user, request=None):
    grn = grn.__class__.objects.select_for_update().get(pk=grn.pk)
    if grn.is_confirmed:
        return grn
    for item in grn.items.select_related("product", "variant").all():
        regular = int(item.regular_accepted_quantity or 0)
        restricted = int(item.restricted_accepted_quantity or 0)
        if regular + restricted == 0:
            regular = int(item.accepted_quantity or 0)
        if regular:
            adjust_classified_stock(
                product=item.product,
                variant=item.variant,
                branch=grn.branch,
                warehouse=grn.warehouse_location,
                quantity=regular,
                classification="REGULAR",
                movement_type="PURCHASE_REGULAR",
                performed_by=user,
                reference_type="GRN",
                reference_id=grn.pk,
                remarks=f"PO {grn.purchase_order.po_number}",
            )
        if restricted:
            adjust_classified_stock(
                product=item.product,
                variant=item.variant,
                branch=grn.branch,
                warehouse=grn.warehouse_location,
                quantity=restricted,
                classification="RESTRICTED",
                movement_type="PURCHASE_RESTRICTED",
                performed_by=user,
                reference_type="GRN",
                reference_id=grn.pk,
                remarks=f"PO {grn.purchase_order.po_number}",
            )
        po_item = (
            grn.purchase_order.items.select_for_update()
            .filter(product=item.product, variant=item.variant)
            .first()
        )
        if po_item:
            po_item.received_regular_quantity += regular
            po_item.received_restricted_quantity += restricted
            po_item.received_quantity = (
                po_item.received_regular_quantity + po_item.received_restricted_quantity
            )
            po_item.save(
                update_fields=[
                    "received_regular_quantity",
                    "received_restricted_quantity",
                    "received_quantity",
                ]
            )
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


def calculate_purchase_line(
    *,
    regular_quantity,
    restricted_quantity,
    unit_price,
    discount_amount=0,
    tax_treatment="STANDARD_VAT",
    tax_rate=5,
):
    qty = Decimal(str(regular_quantity or 0)) + Decimal(str(restricted_quantity or 0))
    subtotal = qty * Decimal(str(unit_price or 0)) - Decimal(str(discount_amount or 0))
    rate = (
        Decimal(str(tax_rate or 0)) if tax_treatment == "STANDARD_VAT" else Decimal("0")
    )
    tax = (subtotal * rate / Decimal("100")).quantize(Decimal("0.01"))
    return {
        "quantity": qty,
        "subtotal": subtotal,
        "tax_amount": tax,
        "line_total": subtotal + tax,
    }
