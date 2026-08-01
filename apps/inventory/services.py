from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.notifications.services import notify_branch
from apps.common.tax import calculate_inventory_tax, quantize_money, quantize_unit

from .models import ProductStock, StockMovement

REGULAR_CLASSIFICATION = "REGULAR"
RESTRICTED_CLASSIFICATION = "RESTRICTED"

RESTRICTED_MOVEMENT_TYPES = {
    "PURCHASE_RESTRICTED",
    "SALE_RESTRICTED",
}


def generate_stock_number(prefix="SM"):
    return f"{prefix}-{timezone.now():%Y%m%d%H%M%S%f}"


def _resolve_classification(movement_type, stock_classification=None):
    """Return a normalized stock classification for a movement."""
    if stock_classification:
        classification = str(stock_classification).strip().upper()
    elif movement_type in RESTRICTED_MOVEMENT_TYPES:
        classification = RESTRICTED_CLASSIFICATION
    else:
        # Existing OPENING, PURCHASE, SALE, ADJUSTMENT, TRANSFER and return
        # flows are treated as regular stock unless explicitly classified.
        classification = REGULAR_CLASSIFICATION

    if classification not in {
        REGULAR_CLASSIFICATION,
        RESTRICTED_CLASSIFICATION,
    }:
        raise ValueError("Invalid stock classification.")

    return classification


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
    stock_classification=None,
    warehouse="",
    unit_cost=None,
    vat_percentage=0,
    vat_treatment="OUT_OF_SCOPE",
    vat_inclusive=False,
    vat_recoverable=True,
    tax_invoice_number="",
    tax_invoice_date=None,
    source_document_number="",
):
    """
    Apply a signed stock quantity to one product/variant stock record.

    Positive quantity increases stock and negative quantity decreases stock.
    Older callers that do not send a classification are treated as REGULAR.
    This keeps product opening stock, adjustments, purchases and existing
    sales flows backward compatible with classified inventory.
    """
    if variant and variant.product_id != product.id:
        raise ValueError("The selected variant does not belong to the product.")

    quantity = int(quantity)
    classification = _resolve_classification(
        movement_type,
        stock_classification,
    )

    lookup = {
        "product": product,
        "branch": branch,
        "variant": variant,
    }

    stock, _created = ProductStock.objects.select_for_update().get_or_create(
        **lookup,
        defaults={
            "reorder_level": product.reorder_level,
            "warehouse": warehouse or "",
            "current_stock": 0,
            "reserved_stock": 0,
            "regular_quantity": 0,
            "restricted_quantity": 0,
            "reserved_regular_quantity": 0,
            "reserved_restricted_quantity": 0,
        },
    )

    # Keep a warehouse value when supplied. The current ProductStock schema
    # uses one stock row per product/variant/branch, so this is descriptive.
    if warehouse and not stock.warehouse:
        stock.warehouse = warehouse

    if classification == RESTRICTED_CLASSIFICATION:
        previous_balance = int(stock.restricted_quantity or 0)
        new_balance = previous_balance + quantity

        if new_balance < 0 and not allow_negative:
            raise ValueError(
                f"Insufficient restricted stock for {product.sku}. "
                f"Available restricted stock: {stock.available_restricted_quantity}."
            )

        stock.restricted_quantity = new_balance
    else:
        previous_balance = int(stock.regular_quantity or 0)
        new_balance = previous_balance + quantity

        if new_balance < 0 and not allow_negative:
            raise ValueError(
                f"Insufficient regular stock for {product.sku}. "
                f"Available regular stock: {stock.available_regular_quantity}."
            )

        stock.regular_quantity = new_balance

    # Synchronize fields still used by older screens, filters and reports.
    stock.sync_legacy_balances()
    stock.reorder_level = product.reorder_level

    valuation = calculate_inventory_tax(
        unit_cost=(
            unit_cost
            if unit_cost is not None
            else stock.average_unit_cost_excluding_vat
        ),
        vat_percentage=vat_percentage,
        tax_treatment=vat_treatment,
        vat_inclusive=vat_inclusive,
        recoverable=vat_recoverable,
    )

    # Weighted-average valuation is recalculated only for positive receipts with
    # an explicit cost. Outgoing movements retain the existing carrying cost.
    if quantity > 0 and unit_cost is not None:
        old_quantity = max(0, stock.total_quantity - quantity)
        old_value = Decimal(old_quantity) * Decimal(stock.average_unit_cost or 0)
        incoming_value = Decimal(quantity) * valuation["capitalized_unit_cost"]
        new_total_quantity = max(0, stock.total_quantity)
        stock.average_unit_cost = quantize_unit(
            (old_value + incoming_value) / Decimal(new_total_quantity)
            if new_total_quantity
            else valuation["capitalized_unit_cost"]
        )
        stock.average_unit_cost_excluding_vat = valuation["unit_cost_excluding_vat"]
        stock.recoverable_vat_per_unit = valuation["recoverable_vat_per_unit"]
        stock.capitalized_vat_per_unit = valuation["capitalized_vat_per_unit"]
        stock.last_purchase_cost_excluding_vat = valuation["unit_cost_excluding_vat"]
        stock.last_purchase_cost = quantize_unit(
            valuation["unit_cost_excluding_vat"] + valuation["vat_per_unit"]
        )
        stock.last_tax_treatment = str(vat_treatment or "OUT_OF_SCOPE").upper()
        stock.last_vat_percentage = Decimal(str(vat_percentage or 0))
        stock.valuation_updated_at = timezone.now()

    update_fields = [
        "regular_quantity",
        "restricted_quantity",
        "current_stock",
        "reserved_stock",
        "reorder_level",
        "last_stock_update",
        "average_unit_cost_excluding_vat",
        "recoverable_vat_per_unit",
        "capitalized_vat_per_unit",
        "average_unit_cost",
        "last_purchase_cost_excluding_vat",
        "last_purchase_cost",
        "last_tax_treatment",
        "last_vat_percentage",
        "valuation_updated_at",
        "updated_at",
    ]

    if warehouse and stock.warehouse == warehouse:
        update_fields.append("warehouse")

    stock.save(update_fields=list(dict.fromkeys(update_fields)))

    movement = StockMovement.objects.create(
        movement_number=generate_stock_number(),
        product=product,
        variant=variant,
        branch=branch,
        movement_type=movement_type,
        stock_classification=classification,
        warehouse=warehouse or stock.warehouse or "",
        quantity=quantity,
        # These balances represent the selected classification, not a silently
        # combined stock balance.
        previous_stock=previous_balance,
        new_stock=new_balance,
        reference_type=reference_type,
        reference_id=str(reference_id or ""),
        remarks=remarks,
        performed_by=performed_by,
        quantity_before=previous_balance,
        quantity_after=new_balance,
        unit_cost_excluding_vat=valuation["unit_cost_excluding_vat"],
        vat_treatment=str(vat_treatment or "OUT_OF_SCOPE").upper(),
        vat_percentage=Decimal(str(vat_percentage or 0)),
        recoverable_vat_amount=quantize_money(
            abs(Decimal(quantity)) * valuation["recoverable_vat_per_unit"]
        ),
        non_recoverable_vat_amount=quantize_money(
            abs(Decimal(quantity)) * valuation["capitalized_vat_per_unit"]
        ),
        capitalized_unit_cost=stock.average_unit_cost,
        net_value_change=quantize_money(Decimal(quantity) * stock.average_unit_cost),
        gross_value_change=quantize_money(
            Decimal(quantity)
            * (valuation["unit_cost_excluding_vat"] + valuation["vat_per_unit"])
        ),
        running_stock_value=quantize_money(
            Decimal(stock.total_quantity) * stock.average_unit_cost
        ),
        source_document_type=reference_type,
        source_document_number=source_document_number or str(reference_id or ""),
        tax_invoice_number=tax_invoice_number,
        tax_invoice_date=tax_invoice_date,
        is_vat_relevant=str(vat_treatment or "").upper()
        in {"STANDARD_VAT", "REVERSE_CHARGE"},
    )

    if stock.available_stock < 10:
        notify_branch(
            branch,
            "LOW_STOCK",
            "Low Stock Alert",
            (
                f"{product.product_name} is low in stock. "
                f"Available: {stock.available_stock}. "
                "Low-stock threshold: below 10."
            ),
            "WARNING",
        )

    return movement
