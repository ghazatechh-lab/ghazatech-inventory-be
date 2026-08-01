from decimal import Decimal, ROUND_HALF_UP

MONEY = Decimal("0.01")
FOUR_DP = Decimal("0.0001")
DEFAULT_VAT_PERCENTAGE = Decimal("5.00")

TAX_TREATMENTS = {
    "STANDARD_VAT",
    "ZERO_RATED",
    "EXEMPT",
    "OUT_OF_SCOPE",
    "REVERSE_CHARGE",
}


def decimal_value(value):
    return Decimal(str(value or 0))


def quantize_money(value):
    return decimal_value(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def quantize_unit(value):
    return decimal_value(value).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def calculate_inventory_tax(
    *,
    unit_cost,
    vat_percentage=None,
    tax_treatment="OUT_OF_SCOPE",
    vat_inclusive=False,
    recoverable=True
):
    treatment = str(tax_treatment or "OUT_OF_SCOPE").upper()
    # The system uses one configured UAE VAT rate: 5%.
    # Non-taxable treatments always use 0%, regardless of client input.
    rate = (
        DEFAULT_VAT_PERCENTAGE
        if treatment in {"STANDARD_VAT", "REVERSE_CHARGE"}
        else Decimal("0.00")
    )
    entered_cost = decimal_value(unit_cost)

    vat_applicable = treatment in {"STANDARD_VAT", "REVERSE_CHARGE"} and rate > 0
    if not vat_applicable:
        return {
            "unit_cost_excluding_vat": quantize_unit(entered_cost),
            "vat_per_unit": Decimal("0.0000"),
            "recoverable_vat_per_unit": Decimal("0.0000"),
            "capitalized_vat_per_unit": Decimal("0.0000"),
            "capitalized_unit_cost": quantize_unit(entered_cost),
        }

    if vat_inclusive:
        base = entered_cost / (Decimal("1") + (rate / Decimal("100")))
        vat = entered_cost - base
    else:
        base = entered_cost
        vat = base * rate / Decimal("100")

    recoverable_vat = vat if recoverable else Decimal("0")
    capitalized_vat = Decimal("0") if recoverable else vat

    return {
        "unit_cost_excluding_vat": quantize_unit(base),
        "vat_per_unit": quantize_unit(vat),
        "recoverable_vat_per_unit": quantize_unit(recoverable_vat),
        "capitalized_vat_per_unit": quantize_unit(capitalized_vat),
        "capitalized_unit_cost": quantize_unit(base + capitalized_vat),
    }
