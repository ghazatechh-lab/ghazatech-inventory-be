from django.db import transaction
from django.utils import timezone
from .models import ProductStock, StockMovement
from apps.notifications.services import notify_branch


@transaction.atomic
def adjust_stock(
    *,
    product,
    branch,
    quantity,
    movement_type,
    performed_by=None,
    reference_type="",
    reference_id="",
    remarks="",
    allow_negative=False,
):
    stock, _ = ProductStock.objects.select_for_update().get_or_create(
        product=product,
        branch=branch,
        defaults={"reorder_level": product.reorder_level},
    )
    old = stock.current_stock
    new = old + quantity
    if new < 0 and not allow_negative:
        raise ValueError(
            f"Insufficient stock for {product.sku}; available {stock.available_stock}"
        )
    stock.current_stock = new
    stock.save(update_fields=["current_stock", "last_stock_update", "updated_at"])
    movement = StockMovement.objects.create(
        movement_number=f"SM-{timezone.now():%Y%m%d%H%M%S%f}",
        product=product,
        branch=branch,
        movement_type=movement_type,
        quantity=quantity,
        previous_stock=old,
        new_stock=new,
        reference_type=reference_type,
        reference_id=str(reference_id),
        remarks=remarks,
        performed_by=performed_by,
    )
    if stock.available_stock <= stock.reorder_level:
        notify_branch(
            branch,
            "LOW_STOCK",
            "Low Stock Alert",
            f"{product.product_name} is low in stock. Available: {stock.available_stock}",
            "WARNING",
        )
    return movement
