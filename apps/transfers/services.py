from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.inventory.models import ProductStock
from apps.inventory.services import adjust_stock, resolve_or_create_destination_catalog_product
from apps.branch_data.services import database_alias_for_branch


def _resolve_stock_rows(item, branch, *, lock=False):
    """Return physical stock rows for this transfer item from the branch DB."""
    using = database_alias_for_branch(branch)
    manager = ProductStock.objects.using(using)
    queryset = manager.filter(
        product_id=item.product_id,
        branch_id=branch.id,
        variant_id=(item.variant_id if item.variant_id else None),
    ).order_by("warehouse", "id")
    if not lock:
        return list(queryset)
    with transaction.atomic(using=using):
        return list(queryset.select_for_update())


def _resolve_stock(item, branch, *, lock=False):
    rows = _resolve_stock_rows(item, branch, lock=lock)
    if not rows:
        return None
    # Prefer the canonical/default warehouse row, otherwise the first row with
    # available stock. This preserves legacy behavior for callers expecting one row.
    return next((row for row in rows if not (row.warehouse or "").strip()), None) or next(
        (row for row in rows if row.available_stock > 0), rows[0]
    )


def _available_quantity(item, branch, *, lock=False):
    return sum(
        int(row.available_stock or 0)
        for row in _resolve_stock_rows(item, branch, lock=lock)
    )


def dispatch(t, u):
    status = str(t.status or "").upper()
    if status != "APPROVED":
        raise serializers.ValidationError(
            {"status": "Only approved transfers can be dispatched."}
        )

    source_db = database_alias_for_branch(t.from_branch)
    items = list(t.items.select_related("product", "variant"))

    with transaction.atomic(using=source_db):
        locked = []
        errors = []
        for item in items:
            quantity = int(item.dispatched_quantity or item.requested_quantity or 0)
            rows = _resolve_stock_rows(item, t.from_branch, lock=True)
            available = sum(int(row.available_stock or 0) for row in rows)
            label = item.product.sku
            if item.variant_id:
                label = f"{label} ({item.variant})"
            if quantity > available:
                errors.append(
                    f"{label}: requested {quantity}, available {available} in "
                    f"{t.from_branch.branch_code}."
                )
            locked.append((item, rows, quantity))

        if errors:
            raise serializers.ValidationError(
                {"items": ["Insufficient stock in the source branch. " + " ".join(errors)]}
            )

        for item, rows, quantity in locked:
            remaining = quantity
            for stock in rows:
                if remaining <= 0:
                    break
                row_available = max(0, int(stock.available_stock or 0))
                if row_available <= 0:
                    continue
                deduct = min(remaining, row_available)
                adjust_stock(
                    product=item.product,
                    variant=stock.variant,
                    branch=t.from_branch,
                    warehouse=stock.warehouse or "",
                    quantity=-deduct,
                    movement_type="TRANSFER_OUT",
                    performed_by=u,
                    reference_type="Transfer",
                    reference_id=t.id,
                    remarks=f"Transfer {t.transfer_number} to {t.to_branch.branch_code}",
                    unit_cost=item.transfer_unit_cost,
                    vat_treatment="NON_VAT",
                    source_document_number=t.transfer_number,
                )
                remaining -= deduct

            item.dispatched_quantity = quantity
            item.save(update_fields=["dispatched_quantity"])

    with transaction.atomic():
        t.status = "IN_TRANSIT"
        t.dispatched_by = u
        t.dispatch_date = timezone.localdate()
        t.dispatched_at = timezone.now()
        t.save(
            update_fields=[
                "status", "dispatched_by", "dispatch_date", "dispatched_at", "updated_at"
            ]
        )
    return t


def receive(t, u):
    status = str(t.status or "").upper()
    if status not in {"DISPATCHED", "IN_TRANSIT"}:
        raise serializers.ValidationError(
            {"status": "Only dispatched transfers can be received."}
        )

    destination_db = database_alias_for_branch(t.to_branch)

    with transaction.atomic(using=destination_db):
        for item in t.items.select_related("product", "variant"):
            quantity = item.received_quantity or max(
                0, item.dispatched_quantity - item.damaged_quantity
            )
            destination_product, destination_variant = resolve_or_create_destination_catalog_product(
                item.product, t.to_branch, source_variant=item.variant
            )
            adjust_stock(
                product=destination_product,
                variant=destination_variant,
                branch=t.to_branch,
                quantity=quantity,
                movement_type="TRANSFER_IN",
                performed_by=u,
                reference_type="Transfer",
                reference_id=t.id,
                remarks=f"Transfer {t.transfer_number} from {t.from_branch.branch_code}",
                unit_cost=item.transfer_unit_cost,
                vat_treatment="OUT_OF_SCOPE",
                source_document_number=t.transfer_number,
            )
            item.received_quantity = quantity
            item.destination_value = Decimal(quantity) * Decimal(
                item.transfer_unit_cost or 0
            )
            item.value_difference = item.destination_value - Decimal(item.source_value or 0)
            item.save(
                update_fields=["received_quantity", "destination_value", "value_difference"]
            )

    t.status = "RECEIVED"
    t.received_by = u
    t.received_date = timezone.localdate()
    t.received_at = timezone.now()
    destination_value = sum(
        (Decimal(item.destination_value or 0) for item in t.items.all()), Decimal("0")
    )
    t.destination_stock_value = destination_value
    t.value_difference = destination_value - Decimal(t.source_stock_value or 0)
    t.reconciliation_status = "MATCHED" if t.value_difference == 0 else "VARIANCE"
    t.save(
        update_fields=[
            "status",
            "received_by",
            "received_date",
            "received_at",
            "destination_stock_value",
            "value_difference",
            "reconciliation_status",
            "updated_at",
        ]
    )
    return t
