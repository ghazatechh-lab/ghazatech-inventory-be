from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.tax import calculate_inventory_tax, quantize_money, quantize_unit
from apps.notifications.services import notify_branch

from .models import ProductStock, StockMovement

VAT = "VAT"
ZERO_VAT = "ZERO_VAT"
NON_VAT = "NON_VAT"
VALID_TAX_TREATMENTS = {VAT, ZERO_VAT, NON_VAT}


def generate_stock_number(prefix="SM"):
    return f"{prefix}-{timezone.now():%Y%m%d%H%M%S%f}"


def normalize_tax(product, vat_treatment=None, vat_percentage=None):
    """Return the inventory tax treatment and effective VAT percentage.

    VAT products use the UAE standard 5% rate. ZERO_VAT and NON_VAT products
    always use 0%. ZERO_VAT remains a taxable zero-rated supply, whereas
    NON_VAT is outside the VAT calculation.
    """
    treatment = (
        str(vat_treatment or getattr(product, "tax_treatment", NON_VAT) or NON_VAT)
        .strip()
        .upper()
    )

    if treatment not in VALID_TAX_TREATMENTS:
        raise ValueError("Invalid VAT treatment. Select VAT, Zero VAT, or Non-VAT.")

    # Keep the service strict and consistent with the product tax choices.
    percentage = Decimal("5.00") if treatment == VAT else Decimal("0.00")
    return treatment, percentage


def _common_tax_treatment(treatment):
    """Map product tax choices to the shared tax utility choices."""
    return {
        VAT: "STANDARD_VAT",
        ZERO_VAT: "ZERO_RATED",
        NON_VAT: "OUT_OF_SCOPE",
    }[treatment]


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
    warehouse="",
    unit_cost=None,
    vat_percentage=None,
    vat_treatment=None,
    vat_inclusive=None,
    vat_recoverable=True,
    tax_invoice_number="",
    tax_invoice_date=None,
    source_document_number="",
    **_ignored,
):
    """Apply a signed quantity to a unified ProductStock balance.

    Positive quantities increase current_stock and negative quantities reduce
    it. The stock row keeps one physical quantity and one reserved quantity;
    regular/restricted classifications are no longer supported.
    """
    if variant and variant.product_id != product.id:
        raise ValueError("The selected variant does not belong to the product.")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Stock quantity must be a whole number.") from exc

    if quantity == 0:
        raise ValueError("Stock quantity cannot be zero.")

    normalized_warehouse = str(warehouse or "").strip()

    stock, _created = ProductStock.objects.select_for_update().get_or_create(
        product=product,
        branch=branch,
        variant=variant,
        warehouse=normalized_warehouse,
        defaults={
            "reorder_level": product.reorder_level,
            "current_stock": 0,
            "reserved_stock": 0,
        },
    )

    previous_balance = int(stock.current_stock or 0)
    new_balance = previous_balance + quantity

    # ProductStock is intentionally non-negative. Keep allow_negative in the
    # signature for older callers, but never persist an invalid negative stock.
    if new_balance < 0:
        raise ValueError(
            f"Insufficient stock for {product.sku}. "
            f"Available stock: {stock.available_stock}."
        )

    # A physical deduction must not leave reserved stock above current stock.
    # The calling sales/transfer flow should release its reservation first.
    if new_balance < int(stock.reserved_stock or 0) and not allow_negative:
        raise ValueError(
            f"Insufficient available stock for {product.sku}. "
            f"Available stock: {stock.available_stock}."
        )

    stock.current_stock = new_balance
    stock.reorder_level = product.reorder_level

    treatment, percentage = normalize_tax(
        product,
        vat_treatment=vat_treatment,
        vat_percentage=vat_percentage,
    )

    # Inclusive pricing only applies to standard VAT. Zero VAT and Non-VAT
    # always have a zero tax amount and are treated as non-inclusive.
    inclusive = (
        bool(getattr(product, "vat_inclusive", False))
        if vat_inclusive is None
        else bool(vat_inclusive)
    )
    if treatment != VAT:
        inclusive = False

    valuation = calculate_inventory_tax(
        unit_cost=(
            unit_cost
            if unit_cost is not None
            else stock.average_unit_cost_excluding_vat
        ),
        vat_percentage=percentage,
        tax_treatment=_common_tax_treatment(treatment),
        vat_inclusive=inclusive,
        recoverable=bool(vat_recoverable) if treatment == VAT else False,
    )

    # Recalculate weighted-average carrying cost only for positive receipts
    # having an explicit unit cost. Outgoing movements retain carrying cost.
    if quantity > 0 and unit_cost is not None:
        old_quantity = max(0, previous_balance)
        old_value = Decimal(old_quantity) * Decimal(stock.average_unit_cost or 0)
        incoming_value = Decimal(quantity) * valuation["capitalized_unit_cost"]
        total_quantity = max(0, stock.current_stock)

        stock.average_unit_cost = quantize_unit(
            (old_value + incoming_value) / Decimal(total_quantity)
            if total_quantity
            else valuation["capitalized_unit_cost"]
        )
        stock.average_unit_cost_excluding_vat = valuation["unit_cost_excluding_vat"]
        stock.recoverable_vat_per_unit = valuation["recoverable_vat_per_unit"]
        stock.capitalized_vat_per_unit = valuation["capitalized_vat_per_unit"]
        stock.last_purchase_cost_excluding_vat = valuation["unit_cost_excluding_vat"]
        stock.last_purchase_cost = quantize_unit(
            valuation["unit_cost_excluding_vat"] + valuation["vat_per_unit"]
        )
        stock.last_tax_treatment = treatment
        stock.last_vat_percentage = percentage
        stock.valuation_updated_at = timezone.now()

    stock.save()

    movement = StockMovement.objects.create(
        movement_number=generate_stock_number(),
        product=product,
        variant=variant,
        branch=branch,
        movement_type=movement_type,
        warehouse=normalized_warehouse,
        quantity=quantity,
        previous_stock=previous_balance,
        new_stock=new_balance,
        reference_type=reference_type,
        reference_id=str(reference_id or ""),
        remarks=remarks,
        performed_by=performed_by,
        quantity_before=previous_balance,
        quantity_after=new_balance,
        unit_cost_excluding_vat=valuation["unit_cost_excluding_vat"],
        vat_treatment=treatment,
        vat_percentage=percentage,
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
            Decimal(stock.current_stock) * stock.average_unit_cost
        ),
        source_document_type=reference_type,
        source_document_number=(source_document_number or str(reference_id or "")),
        tax_invoice_number=tax_invoice_number,
        tax_invoice_date=tax_invoice_date,
        is_vat_relevant=treatment in {VAT, ZERO_VAT},
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
