from django.db import transaction
from apps.inventory.services import adjust_stock


@transaction.atomic
def confirm_grn(grn, user):
    if grn.is_confirmed:
        return grn
    for i in grn.items.select_related("product"):
        q = i.accepted_quantity or max(0, i.received_quantity - i.damaged_quantity)
        adjust_stock(
            product=i.product,
            branch=grn.branch,
            quantity=q,
            movement_type="PURCHASE",
            performed_by=user,
            reference_type="GRN",
            reference_id=grn.id,
        )
        poi = grn.purchase_order.items.filter(product=i.product).first()
        if poi:
            poi.received_quantity += q
            poi.save(update_fields=["received_quantity"])
    grn.is_confirmed = True
    grn.status = "CONFIRMED"
    grn.save(update_fields=["is_confirmed", "status", "updated_at"])
    return grn
