from decimal import Decimal

from django.db import transaction

from apps.audit_logs.services import create_immutable_audit
from apps.common.sensitive_permissions import has_sensitive_permission
from apps.inventory.services import adjust_stock

# New product tax treatments plus legacy sales values retained temporarily so
# existing records and migrations remain readable until the sales module is
# migrated fully.
TAX_TREATMENTS = {
    "VAT",
    "ZERO_VAT",
    "NON_VAT",
    "STANDARD_VAT",
    "ZERO_RATED",
    "EXEMPT",
    "OUT_OF_SCOPE",
    "REVERSE_CHARGE",
}

STANDARD_VAT_TREATMENTS = {"VAT", "STANDARD_VAT"}
ZERO_VAT_TREATMENTS = {"ZERO_VAT", "ZERO_RATED"}
NON_VAT_TREATMENTS = {
    "NON_VAT",
    "EXEMPT",
    "OUT_OF_SCOPE",
    "REVERSE_CHARGE",
}


def normalize_tax_treatment(value):
    treatment = str(value or "VAT").strip().upper()

    if treatment == "STANDARD_VAT":
        return "VAT"
    if treatment == "ZERO_RATED":
        return "ZERO_VAT"
    if treatment in {"EXEMPT", "OUT_OF_SCOPE", "REVERSE_CHARGE"}:
        return "NON_VAT"

    return treatment


def calculate_sales_line(
    *,
    quantity,
    unit_price,
    discount=0,
    tax_treatment="VAT",
    tax_rate=5,
    tax_inclusive=False,
):
    treatment = normalize_tax_treatment(tax_treatment)

    gross = Decimal(str(quantity or 0)) * Decimal(str(unit_price or 0)) - Decimal(
        str(discount or 0)
    )

    if treatment == "VAT":
        rate = Decimal("5.00")
    else:
        rate = Decimal("0.00")
        tax_inclusive = False

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


def validate_tax_treatment(user, tax_treatment, reason=""):
    treatment = str(tax_treatment or "VAT").strip().upper()

    if treatment not in TAX_TREATMENTS:
        raise ValueError("Invalid tax treatment.")

    normalized = normalize_tax_treatment(treatment)
    non_standard = normalized != "VAT"

    if non_standard and not has_sensitive_permission(
        user,
        "create_non_standard_tax_sale",
    ):
        raise PermissionError(
            "You do not have permission to use Zero VAT or Non-VAT treatment."
        )

    if non_standard and not str(reason or "").strip():
        raise ValueError(
            "A legal reason or supporting reference is required "
            "for Zero VAT or Non-VAT sales."
        )

    return normalized


# Temporary compatibility wrapper for existing serializers/views that still
# call the old function name with stock_classification. Classification is
# intentionally ignored because inventory now maintains one quantity.
def validate_tax_and_classification(
    user,
    tax_treatment,
    stock_classification=None,
    reason="",
):
    return validate_tax_treatment(user, tax_treatment, reason)


@transaction.atomic
def deduct_sales_item(
    *,
    item,
    branch,
    user,
    reference_type,
    reference_id,
    request=None,
):
    normalized_tax_treatment = validate_tax_treatment(
        user,
        getattr(item, "tax_treatment", "VAT"),
        getattr(item, "tax_reason", ""),
    )

    movement = adjust_stock(
        product=item.product,
        variant=item.variant,
        branch=branch,
        quantity=-int(item.quantity),
        movement_type="SALE",
        performed_by=user,
        reference_type=reference_type,
        reference_id=reference_id,
        remarks=getattr(item, "tax_reason", "")
        or getattr(item, "description", "")
        or "",
        vat_percentage=(
            Decimal("5.00") if normalized_tax_treatment == "VAT" else Decimal("0.00")
        ),
        vat_treatment=normalized_tax_treatment,
        vat_inclusive=False,
        vat_recoverable=False,
    )

    create_immutable_audit(
        user=user,
        branch=branch,
        action="SALE_STOCK_DEDUCTED",
        obj=item,
        after={
            "quantity": str(item.quantity),
            "tax_treatment": normalized_tax_treatment,
        },
        request=request,
        reason=getattr(item, "tax_reason", ""),
    )

    return movement
