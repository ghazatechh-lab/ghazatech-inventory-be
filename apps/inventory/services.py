from django.db import transaction
from django.utils import timezone

from apps.notifications.services import notify_branch

from .models import ProductStock, StockMovement


def generate_stock_number(prefix="SM"):
    return f"{prefix}-" f"{timezone.now():%Y%m%d%H%M%S%f}"


@transaction.atomic
def adjust_stock(
    *,
    product,
    branch,
    quantity,
    movement_type,
    variant=None,
    performed_by=None,
    reference_type="",
    reference_id="",
    remarks="",
    allow_negative=False,
):
    """
    Apply a signed stock quantity to one product/variant in one branch.

    Positive quantity increases stock.
    Negative quantity decreases stock.
    """
    if variant and variant.product_id != product.id:
        raise ValueError("The selected variant does not belong to the product.")

    lookup = {
        "product": product,
        "branch": branch,
        "variant": variant,
    }

    stock, _ = ProductStock.objects.select_for_update().get_or_create(
        **lookup,
        defaults={
            "reorder_level": product.reorder_level,
        },
    )

    previous_stock = stock.current_stock
    new_stock = previous_stock + int(quantity)

    if new_stock < 0 and not allow_negative:
        raise ValueError(
            f"Insufficient stock for {product.sku}. "
            f"Current stock: {previous_stock}."
        )

    stock.current_stock = new_stock
    stock.reorder_level = product.reorder_level
    stock.save(
        update_fields=[
            "current_stock",
            "reorder_level",
            "last_stock_update",
            "updated_at",
        ]
    )

    movement = StockMovement.objects.create(
        movement_number=generate_stock_number(),
        product=product,
        variant=variant,
        branch=branch,
        movement_type=movement_type,
        quantity=int(quantity),
        previous_stock=previous_stock,
        new_stock=new_stock,
        reference_type=reference_type,
        reference_id=str(reference_id or ""),
        remarks=remarks,
        performed_by=performed_by,
    )

    if stock.available_stock < 10:
        notify_branch(
            branch,
            "LOW_STOCK",
            "Low Stock Alert",
            (
                f"{product.product_name} is low in stock. "
                f"Available: {stock.available_stock}. Low-stock threshold: below 10."
            ),
            "WARNING",
        )

    return movement
