from decimal import Decimal
from django.db import transaction

from apps.audit_logs.services import create_immutable_audit
from apps.common.sensitive_permissions import has_sensitive_permission
from apps.inventory.classified_stock import adjust_classified_stock

TAX_TREATMENTS = {
    "STANDARD_VAT",
    "ZERO_RATED",
    "EXEMPT",
    "OUT_OF_SCOPE",
    "REVERSE_CHARGE",
}


def calculate_sales_line(
    *,
    quantity,
    unit_price,
    discount=0,
    tax_treatment="STANDARD_VAT",
    tax_rate=5,
    tax_inclusive=False
):
    gross = Decimal(str(quantity or 0)) * Decimal(str(unit_price or 0)) - Decimal(
        str(discount or 0)
    )
    rate = (
        Decimal(str(tax_rate or 0)) if tax_treatment == "STANDARD_VAT" else Decimal("0")
    )
    if tax_inclusive and rate:
        taxable = gross / (Decimal("1") + rate / Decimal("100"))
        tax = gross - taxable
        total = gross
    else:
        taxable = gross
        tax = taxable * rate / Decimal("100")
        total = taxable + tax
    return {
        "taxable_amount": taxable.quantize(Decimal("0.01")),
        "tax_amount": tax.quantize(Decimal("0.01")),
        "line_total": total.quantize(Decimal("0.01")),
    }


def validate_tax_and_classification(
    user, tax_treatment, stock_classification, reason=""
):
    if tax_treatment not in TAX_TREATMENTS:
        raise ValueError("Invalid tax treatment.")
    non_standard = tax_treatment != "STANDARD_VAT"
    if non_standard and not has_sensitive_permission(
        user, "create_non_standard_tax_sale"
    ):
        raise PermissionError("You cannot create a non-standard-tax sale.")
    if stock_classification == "RESTRICTED" and not has_sensitive_permission(
        user, "manage_restricted_stock"
    ):
        raise PermissionError("You cannot consume restricted stock.")
    if non_standard and not str(reason or "").strip():
        raise ValueError("A legal reason or supporting reference is required.")


@transaction.atomic
def deduct_sales_item(
    *, item, branch, user, reference_type, reference_id, request=None
):
    validate_tax_and_classification(
        user, item.tax_treatment, item.stock_classification, item.tax_reason
    )
    movement_type = (
        "SALE_RESTRICTED"
        if item.stock_classification == "RESTRICTED"
        else "SALE_REGULAR"
    )
    movement = adjust_classified_stock(
        product=item.product,
        variant=item.variant,
        branch=branch,
        quantity=-int(item.quantity),
        classification=item.stock_classification,
        movement_type=movement_type,
        performed_by=user,
        reference_type=reference_type,
        reference_id=reference_id,
        remarks=item.tax_reason or item.description or "",
    )
    create_immutable_audit(
        user=user,
        branch=branch,
        action=(
            "RESTRICTED_STOCK_SOLD"
            if item.stock_classification == "RESTRICTED"
            else "SALE_STOCK_DEDUCTED"
        ),
        obj=item,
        after={
            "classification": item.stock_classification,
            "quantity": str(item.quantity),
            "tax_treatment": item.tax_treatment,
        },
        request=request,
        reason=item.tax_reason,
    )
    return movement
