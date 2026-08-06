from decimal import Decimal

from .services import confirm_grn


def confirm_classified_grn(grn, user, request=None):
    """Deprecated name kept only so old imports continue to start."""
    return confirm_grn(grn, user, request=request)


def calculate_purchase_line(
    *, quantity, unit_price, discount_amount=0, tax_treatment="STANDARD_VAT", tax_rate=5
):
    qty = Decimal(str(quantity or 0))
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
