from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.tax import calculate_inventory_tax, quantize_money, quantize_unit
from apps.common.transactions import routed_atomic
from apps.branch_data.services import database_alias_for_branch
from apps.notifications.services import notify_branch

from .models import Brand, Category, Product, ProductVariant, Rack, ProductStock, StockMovement


VAT = "VAT"
ZERO_VAT = "ZERO_VAT"
NON_VAT = "NON_VAT"
VALID_TAX_TREATMENTS = {VAT, ZERO_VAT, NON_VAT}


def ensure_catalog_in_branch_db(product, branch, variant=None):
    """Ensure catalog FK rows exist in the physical branch database.

    The shared/default catalog remains authoritative. Physical VAT/NON_VAT
    databases keep same-PK mirrors so ProductStock and StockMovement foreign
    keys are valid. This is intentionally called from the stock service so
    every stock-in path (product opening stock, GRN, transfer receive, returns,
    adjustments) gets the same protection.
    """
    using = database_alias_for_branch(branch)
    if using == "default":
        return using

    product_id = getattr(product, "pk", product)
    variant_id = getattr(variant, "pk", variant) if variant is not None else None

    product_exists = Product.objects.using(using).filter(pk=product_id).exists()
    variant_exists = (
        variant_id is None
        or ProductVariant.objects.using(using).filter(pk=variant_id).exists()
    )
    if product_exists and variant_exists:
        return using

    source_db = getattr(getattr(product, "_state", None), "db", None) or "default"
    source_product = (
        Product.objects.using(source_db)
        .select_related("brand", "category", "rack")
        .filter(pk=product_id)
        .first()
    )
    if source_product is None and source_db != "default":
        source_product = (
            Product.objects.using("default")
            .select_related("brand", "category", "rack")
            .filter(pk=product_id)
            .first()
        )
    if source_product is None:
        raise ValueError(f"Product {product_id} could not be resolved for branch stock.")

    Brand.objects.using(using).update_or_create(
        pk=source_product.brand_id,
        defaults={
            "name": source_product.brand.name,
            "is_active": source_product.brand.is_active,
        },
    )
    Category.objects.using(using).update_or_create(
        pk=source_product.category_id,
        defaults={
            "name": source_product.category.name,
            "is_active": source_product.category.is_active,
        },
    )

    rack_id = source_product.rack_id
    if rack_id:
        source_rack = Rack.objects.using(source_db).filter(pk=rack_id).first()
        if source_rack is None and source_db != "default":
            source_rack = Rack.objects.using("default").filter(pk=rack_id).first()
        if source_rack is not None:
            Rack.objects.using(using).update_or_create(
                pk=source_rack.pk,
                defaults={
                    "branch_id": source_rack.branch_id,
                    "rack_code": source_rack.rack_code,
                    "rack_name": source_rack.rack_name,
                    "is_active": source_rack.is_active,
                },
            )

    supplier_id = source_product.supplier_id
    if supplier_id:
        from apps.suppliers.models import Supplier
        if not Supplier.objects.using(using).filter(pk=supplier_id).exists():
            supplier_id = None

    Product.objects.using(using).update_or_create(
        pk=source_product.pk,
        defaults={
            "product_name": source_product.product_name,
            "sku": source_product.sku,
            "barcode": source_product.barcode,
            "brand_id": source_product.brand_id,
            "category_id": source_product.category_id,
            "branch_id": source_product.branch_id,
            "rack_id": source_product.rack_id,
            "has_variants": source_product.has_variants,
            "compatible_models": source_product.compatible_models,
            "condition": source_product.condition,
            "unit": source_product.unit,
            "tax_treatment": source_product.tax_treatment,
            "vat_inclusive": source_product.vat_inclusive,
            "vat_rate": source_product.vat_rate,
            "supplier_id": supplier_id,
            "description": source_product.description,
            "product_image": source_product.product_image.name if source_product.product_image else None,
            "warranty_period_days": source_product.warranty_period_days,
            "reorder_level": source_product.reorder_level,
            "is_active": source_product.is_active,
            "is_deleted": source_product.is_deleted,
            "deleted_at": source_product.deleted_at,
            "deleted_by_id": None,
        },
    )

    source_variants = ProductVariant.objects.using(source_db).filter(product_id=source_product.pk)
    if not source_variants.exists() and source_db != "default":
        source_variants = ProductVariant.objects.using("default").filter(product_id=source_product.pk)

    for source_variant in source_variants:
        mirrored, _ = ProductVariant.objects.using(using).update_or_create(
            pk=source_variant.pk,
            defaults={
                "product_id": source_product.pk,
                "attributes": source_variant.attributes,
                "available_qty": source_variant.available_qty,
                "purchase_price": source_variant.purchase_price,
                "retail_price": source_variant.retail_price,
                "wholesale_price": source_variant.wholesale_price,
                "minimum_selling_price": source_variant.minimum_selling_price,
                "is_base": source_variant.is_base,
                "is_active": source_variant.is_active,
            },
        )

        rack_ids = list(source_variant.racks.values_list("id", flat=True))
        for source_rack in Rack.objects.using(source_db).filter(pk__in=rack_ids):
            Rack.objects.using(using).update_or_create(
                pk=source_rack.pk,
                defaults={
                    "branch_id": source_rack.branch_id,
                    "rack_code": source_rack.rack_code,
                    "rack_name": source_rack.rack_name,
                    "is_active": source_rack.is_active,
                },
            )
        mirrored.racks.set(rack_ids)

    return using



def resolve_or_create_destination_catalog_product(source_product, destination_branch, source_variant=None):
    """Resolve/create the destination branch catalog record for a transfer receive.

    Product catalog ownership is branch-specific. A transfer therefore receives
    stock against the destination branch's Product row, reusing an existing
    destination SKU/barcode when present and cloning only when necessary.
    """
    from django.db.models import Q

    source_id = getattr(source_product, "pk", source_product)
    source_db = getattr(getattr(source_product, "_state", None), "db", None) or "default"
    source = (
        Product.objects.using(source_db)
        .select_related("brand", "category", "supplier")
        .filter(pk=source_id)
        .first()
    )
    if source is None and source_db != "default":
        source = (
            Product.objects.using("default")
            .select_related("brand", "category", "supplier")
            .filter(pk=source_id)
            .first()
        )
    if source is None:
        raise ValueError(f"Product {source_id} could not be resolved for transfer receive.")

    lookup = Q(sku__iexact=source.sku)
    if source.barcode:
        lookup |= Q(barcode=source.barcode)

    destination_product = (
        Product.objects.using("default")
        .filter(branch_id=destination_branch.pk, is_deleted=False)
        .filter(lookup)
        .order_by("id")
        .first()
    )

    if destination_product is None:
        destination_product = Product.objects.using("default").create(
            product_name=source.product_name,
            sku=source.sku,
            barcode=source.barcode,
            brand_id=source.brand_id,
            category_id=source.category_id,
            branch_id=destination_branch.pk,
            rack_id=None,
            has_variants=source.has_variants,
            compatible_models=source.compatible_models,
            condition=source.condition,
            unit=source.unit,
            tax_treatment=source.tax_treatment,
            vat_inclusive=source.vat_inclusive,
            vat_rate=source.vat_rate,
            supplier_id=None,
            description=source.description,
            product_image=(source.product_image.name if source.product_image else None),
            warranty_period_days=source.warranty_period_days,
            reorder_level=source.reorder_level,
            is_active=source.is_active,
        )

    destination_variant = None
    source_variant_id = getattr(source_variant, "pk", source_variant) if source_variant is not None else None
    if source_variant_id is not None:
        source_variant_db = getattr(getattr(source_variant, "_state", None), "db", None) or source_db
        sv = ProductVariant.objects.using(source_variant_db).filter(pk=source_variant_id).first()
        if sv is None and source_variant_db != "default":
            sv = ProductVariant.objects.using("default").filter(pk=source_variant_id).first()
        if sv is None:
            raise ValueError(f"Variant {source_variant_id} could not be resolved for transfer receive.")

        destination_variant_query = ProductVariant.objects.using("default").filter(
            product_id=destination_product.pk
        )
        destination_variant = (
            destination_variant_query.filter(is_base=True).first()
            if sv.is_base
            else destination_variant_query.filter(attributes=sv.attributes, is_base=False).first()
        )
        if destination_variant is None:
            destination_variant = ProductVariant.objects.using("default").create(
                product_id=destination_product.pk,
                attributes=sv.attributes,
                available_qty=0,
                purchase_price=sv.purchase_price,
                retail_price=sv.retail_price,
                wholesale_price=sv.wholesale_price,
                minimum_selling_price=sv.minimum_selling_price,
                is_base=sv.is_base,
                is_active=sv.is_active,
            )

    # Create same-PK mirrors in the destination physical database before any
    # ProductStock/StockMovement FK is written there.
    ensure_catalog_in_branch_db(
        destination_product, destination_branch, variant=destination_variant
    )
    return destination_product, destination_variant

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
    treatment = {
        "STANDARD_VAT": VAT,
        "ZERO_RATED": ZERO_VAT,
        "OUT_OF_SCOPE": NON_VAT,
        "NON_TAXABLE": NON_VAT,
        "EXEMPT": NON_VAT,
    }.get(treatment, treatment)

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


@routed_atomic
def _adjust_stock_locked(
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
    using = ensure_catalog_in_branch_db(product, branch, variant=variant)

    stock, _created = ProductStock.objects.using(using).select_for_update().get_or_create(
        product_id=product.pk,
        branch_id=branch.pk,
        variant_id=(variant.pk if variant is not None else None),
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

    stock.save(using=using)

    movement = StockMovement.objects.using(using).create(
        movement_number=generate_stock_number(),
        product_id=product.pk,
        variant_id=(variant.pk if variant is not None else None),
        branch_id=branch.pk,
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


def resolve_unit_cost_excluding_vat(stock, *, product=None, variant=None):
    """Return the best known unit cost excluding recoverable VAT.

    Prefer branch stock valuation populated by GRNs. Fall back to the catalog
    purchase price only when branch valuation has not been established yet.
    """
    product = product or getattr(stock, "product", None)
    variant = variant or getattr(stock, "variant", None)

    candidates = [
        getattr(stock, "average_unit_cost_excluding_vat", None),
        getattr(stock, "last_purchase_cost_excluding_vat", None),
    ]
    for value in candidates:
        value = Decimal(str(value or 0))
        if value > 0:
            return quantize_unit(value)

    gross_last = Decimal(str(getattr(stock, "last_purchase_cost", 0) or 0))
    if gross_last > 0:
        treatment = str(getattr(stock, "last_tax_treatment", "") or "").upper()
        rate = Decimal(str(getattr(stock, "last_vat_percentage", 0) or 0))
        if treatment == VAT and rate > 0:
            return quantize_unit(gross_last / (Decimal("1") + rate / Decimal("100")))
        return quantize_unit(gross_last)

    carrying = Decimal(str(getattr(stock, "average_unit_cost", 0) or 0))
    if carrying > 0:
        return quantize_unit(carrying)

    purchase_price = Decimal(str(getattr(variant, "purchase_price", 0) or 0))
    if purchase_price <= 0 and product is not None:
        base = getattr(product, "variants", None)
        if base is not None:
            base_variant = base.filter(is_base=True).first()
            purchase_price = Decimal(str(getattr(base_variant, "purchase_price", 0) or 0))

    if purchase_price <= 0:
        return Decimal("0.0000")

    treatment = str(getattr(product, "tax_treatment", NON_VAT) or NON_VAT).upper()
    rate = Decimal(str(getattr(product, "vat_rate", 0) or 0))
    inclusive = bool(getattr(product, "vat_inclusive", False))
    if treatment == VAT and inclusive and rate > 0:
        purchase_price = purchase_price / (Decimal("1") + rate / Decimal("100"))
    return quantize_unit(purchase_price)


def adjust_stock(*args, **kwargs):
    """Database-aware stock mutation wrapper.

    PostgreSQL row locks are scoped to a database connection, so the atomic
    block must use the same alias as the branch's ProductStock table.
    """
    branch = kwargs.get("branch")
    if branch is None:
        raise ValueError("branch is required for stock mutation")
    using = database_alias_for_branch(branch)
    with transaction.atomic(using=using):
        return _adjust_stock_locked(*args, **kwargs)
