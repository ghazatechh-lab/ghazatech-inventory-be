from django.db import transaction
from apps.inventory.services import adjust_stock


@transaction.atomic
def dispatch(t, u):
    for i in t.items.select_related("product"):
        q = i.dispatched_quantity or i.requested_quantity
        adjust_stock(
            product=i.product,
            branch=t.from_branch,
            quantity=-q,
            movement_type="TRANSFER_OUT",
            performed_by=u,
            reference_type="Transfer",
            reference_id=t.id,
        )
        i.dispatched_quantity = q
        i.save()
    t.status = "IN_TRANSIT"
    t.dispatched_by = u
    t.save()
    return t


@transaction.atomic
def receive(t, u):
    for i in t.items.select_related("product"):
        q = i.received_quantity or max(0, i.dispatched_quantity - i.damaged_quantity)
        adjust_stock(
            product=i.product,
            branch=t.to_branch,
            quantity=q,
            movement_type="TRANSFER_IN",
            performed_by=u,
            reference_type="Transfer",
            reference_id=t.id,
        )
        i.received_quantity = q
        i.save()
    t.status = "RECEIVED"
    t.received_by = u
    t.save()
    return t
