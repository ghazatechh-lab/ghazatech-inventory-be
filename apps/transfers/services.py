from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.inventory.models import ProductStock
from apps.inventory.services import adjust_stock


def _resolve_stock(item, branch, *, lock=False):
    """Return the exact source stock row represented by a transfer item."""
    manager = ProductStock.objects.select_for_update() if lock else ProductStock.objects
    queryset = manager.filter(product=item.product, branch=branch)

    if item.variant_id:
        return queryset.filter(variant_id=item.variant_id).first()

    base_stock = queryset.filter(variant__isnull=True).first()
    if base_stock:
        return base_stock

    # Backward compatibility for transfers created before variant was stored.
    positive_rows = list(queryset.filter(current_stock__gt=0)[:2])
    if len(positive_rows) == 1:
        return positive_rows[0]
    return None


def _available_quantity(item, branch, *, lock=False):
    stock = _resolve_stock(item, branch, lock=lock)
    return stock.available_stock if stock else 0


@transaction.atomic
def dispatch(t, u):
    status = str(t.status or "").upper()
    if status != "APPROVED":
        raise serializers.ValidationError(
            {"status": "Only approved transfers can be dispatched."}
        )

    items = list(t.items.select_related("product", "variant"))
    errors = []
    resolved = []

    for item in items:
        quantity = item.dispatched_quantity or item.requested_quantity
        stock = _resolve_stock(item, t.from_branch, lock=True)
        available = stock.available_stock if stock else 0
        label = item.product.sku
        if item.variant_id:
            label = f"{label} ({item.variant})"

        if quantity > available:
            errors.append(
                f"{label}: requested {quantity}, available {available} in "
                f"{t.from_branch.branch_code}."
            )
        resolved.append((item, stock, quantity))

    if errors:
        raise serializers.ValidationError(
            {"items": ["Insufficient stock in the source branch. " + " ".join(errors)]}
        )

    for item, stock, quantity in resolved:
        # Use the variant from the actual stock row, including legacy transfers.
        variant = stock.variant if stock else item.variant
        adjust_stock(
            product=item.product,
            variant=variant,
            branch=t.from_branch,
            quantity=-quantity,
            movement_type="TRANSFER_OUT",
            performed_by=u,
            reference_type="Transfer",
            reference_id=t.id,
            remarks=f"Transfer {t.transfer_number} to {t.to_branch.branch_code}",
        )
        if not item.variant_id and variant:
            item.variant = variant
        item.dispatched_quantity = quantity
        item.save(update_fields=["variant", "dispatched_quantity"])

    t.status = "IN_TRANSIT"
    t.dispatched_by = u
    t.dispatch_date = timezone.localdate()
    t.save(update_fields=["status", "dispatched_by", "dispatch_date", "updated_at"])
    return t


@transaction.atomic
def receive(t, u):
    status = str(t.status or "").upper()
    if status not in {"DISPATCHED", "IN_TRANSIT"}:
        raise serializers.ValidationError(
            {"status": "Only dispatched transfers can be received."}
        )

    for item in t.items.select_related("product", "variant"):
        quantity = item.received_quantity or max(
            0, item.dispatched_quantity - item.damaged_quantity
        )
        adjust_stock(
            product=item.product,
            variant=item.variant,
            branch=t.to_branch,
            quantity=quantity,
            movement_type="TRANSFER_IN",
            performed_by=u,
            reference_type="Transfer",
            reference_id=t.id,
            remarks=f"Transfer {t.transfer_number} from {t.from_branch.branch_code}",
        )
        item.received_quantity = quantity
        item.save(update_fields=["received_quantity"])

    t.status = "RECEIVED"
    t.received_by = u
    t.received_date = timezone.localdate()
    t.save(update_fields=["status", "received_by", "received_date", "updated_at"])
    return t
