from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.branch_data.services import database_alias_for_branch
from apps.branches.models import Branch
from apps.suppliers.models import Supplier

from .models import Brand, Category, Product, ProductVariant, Rack

PHYSICAL_BRANCH_CODES = {"BR01", "BR02"}
_UNSET = object()


def canonical_branch(branch_or_id):
    """Resolve BR01/BR02 from the authoritative default database."""
    if branch_or_id is None:
        return None

    qs = Branch.objects.using("default").filter(is_active=True)
    code = str(getattr(branch_or_id, "branch_code", "") or "").strip().upper()
    if code:
        return qs.filter(branch_code__iexact=code).first()

    raw = getattr(branch_or_id, "pk", branch_or_id)
    text = str(raw or "").strip()
    if text.isdigit():
        return qs.filter(pk=int(text)).first()
    if text:
        return qs.filter(branch_code__iexact=text).first()
    return None


def require_physical_branch(branch_or_id):
    branch = canonical_branch(branch_or_id)
    if not branch or str(branch.branch_code).upper() not in PHYSICAL_BRANCH_CODES:
        raise serializers.ValidationError(
            {"branch": "Select Branch 1 or Branch 2. Branch 3 is a combined view only."}
        )
    return branch




def physical_branch_label(branch_or_id):
    branch = require_physical_branch(branch_or_id)
    return {"BR01": "Branch 1", "BR02": "Branch 2"}.get(
        str(branch.branch_code).upper(), branch.branch_name or branch.branch_code
    )


def find_physical_product_by_sku(branch, sku, *, exclude_pk=None):
    """Find one non-deleted product by normalized SKU in the target DB."""
    branch = require_physical_branch(branch)
    using = database_alias_for_branch(branch.id)
    normalized = str(sku or "").strip()
    if not normalized:
        return None
    qs = Product.objects.using(using).filter(
        branch_id=branch.id,
        sku__iexact=normalized,
        is_deleted=False,
    )
    if exclude_pk not in (None, ""):
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


def validate_product_sku_for_branch(*, branch, sku, current_product_id=None):
    """Reject a duplicate SKU before PostgreSQL reaches its unique constraint."""
    branch = require_physical_branch(branch)
    normalized = str(sku or "").strip()
    if not normalized:
        raise serializers.ValidationError({"sku": "SKU is required."})
    duplicate = find_physical_product_by_sku(
        branch, normalized, exclude_pk=current_product_id
    )
    if duplicate is not None:
        raise serializers.ValidationError(
            {"sku": f"{normalized} already exists in {physical_branch_label(branch)}."}
        )
    return normalized


def resolve_variant_in_physical_database(source_variant, target_product, branch):
    """Map a source/shared variant to the correct target physical product variant."""
    if source_variant is None:
        return None
    branch = require_physical_branch(branch)
    using = database_alias_for_branch(branch.id)
    qs = ProductVariant.objects.using(using).filter(product_id=target_product.pk)
    if getattr(source_variant, "is_base", False):
        return qs.filter(is_base=True).first()
    return qs.filter(
        is_base=False, attributes=getattr(source_variant, "attributes", {}) or {}
    ).first()


def validate_supplier_for_branch(*, supplier_id, branch, required=False):
    """Validate a supplier inside the target physical database.

    Supplier primary keys are local to a physical database. A matching numeric
    ID in another database must never be treated as the same supplier.
    """
    if supplier_id in (None, "", 0, "0"):
        if required:
            raise serializers.ValidationError({"supplier": "Select a supplier."})
        return None

    branch = require_physical_branch(branch)
    using = database_alias_for_branch(branch.id)

    try:
        supplier_pk = int(supplier_id)
    except (TypeError, ValueError) as exc:
        raise serializers.ValidationError({"supplier": "Select a valid supplier."}) from exc

    supplier = (
        Supplier.objects.using(using)
        .filter(pk=supplier_pk, branch_id=branch.id, is_deleted=False, is_active=True)
        .first()
    )
    if supplier is None:
        raise serializers.ValidationError(
            {
                "supplier": (
                    f"The selected supplier does not exist in {branch.branch_code}. "
                    "Reload suppliers for the selected branch and choose again."
                )
            }
        )
    return supplier


def physical_product_supplier_id(product, branch=None):
    """Return supplier_id from the product mirror in its physical database."""
    branch = canonical_branch(branch or getattr(product, "branch_id", None))
    if not branch or str(branch.branch_code).upper() not in PHYSICAL_BRANCH_CODES:
        return None
    using = database_alias_for_branch(branch.id)
    return (
        Product.objects.using(using)
        .filter(pk=product.pk, branch_id=branch.id)
        .values_list("supplier_id", flat=True)
        .first()
    )


def _target_brand(source, using):
    if source is None:
        raise serializers.ValidationError({"brand": "Brand is required."})
    target, _ = Brand.objects.using(using).update_or_create(
        name=source.name,
        defaults={"is_active": source.is_active},
    )
    return target


def _target_category(source, using):
    if source is None:
        raise serializers.ValidationError({"category": "Category is required."})
    target, _ = Category.objects.using(using).update_or_create(
        name=source.name,
        defaults={"is_active": source.is_active},
    )
    return target


def _target_rack(source, branch, using):
    if source is None:
        return None
    if source.branch_id != branch.id:
        raise serializers.ValidationError(
            {"rack": "Selected rack does not belong to the selected branch."}
        )
    target, _ = Rack.objects.using(using).update_or_create(
        branch_id=branch.id,
        rack_code=source.rack_code,
        defaults={
            "rack_name": source.rack_name,
            "is_active": source.is_active,
        },
    )
    return target


def ensure_product_catalog_in_database(
    product,
    branch,
    *,
    supplier_id=_UNSET,
    validate_supplier=False,
    strict_racks=True,
    reuse_existing_sku=False,
):
    """Create/update the product catalog mirror in one physical database.

    The default Product row remains the shared catalog identity. Branch-owned
    foreign keys (notably Supplier) are resolved only inside the target DB.
    Brand/category/rack rows are mapped by stable business keys rather than by
    blindly copying foreign-key IDs across databases.
    """
    branch = require_physical_branch(branch)
    using = database_alias_for_branch(branch.id)

    if supplier_id is _UNSET:
        supplier_id = (
            Product.objects.using(using)
            .filter(pk=product.pk, branch_id=branch.id)
            .values_list("supplier_id", flat=True)
            .first()
        )

    target_supplier = None
    if supplier_id not in (None, "", 0, "0") or validate_supplier:
        target_supplier = validate_supplier_for_branch(
            supplier_id=supplier_id,
            branch=branch,
            required=validate_supplier and supplier_id not in (None, ""),
        )

    target_brand = _target_brand(product.brand, using)
    target_category = _target_category(product.category, using)
    if product.rack and product.rack.branch_id != branch.id and not strict_racks:
        target_rack = None
    else:
        target_rack = _target_rack(product.rack, branch, using)

    normalized_sku = str(product.sku or "").strip()
    target_product = (
        Product.objects.using(using)
        .filter(pk=product.pk, branch_id=branch.id)
        .first()
    )
    reused_existing_sku = False
    sku_match = find_physical_product_by_sku(
        branch,
        normalized_sku,
        exclude_pk=(target_product.pk if target_product else None),
    )
    if sku_match is not None:
        if reuse_existing_sku:
            target_product = sku_match
            reused_existing_sku = True
        else:
            raise serializers.ValidationError(
                {
                    "sku": (
                        f"{normalized_sku} already exists in "
                        f"{physical_branch_label(branch)}."
                    )
                }
            )

    product_defaults = {
        "product_name": product.product_name,
        "sku": normalized_sku,
        "barcode": product.barcode,
        "brand_id": target_brand.pk,
        "category_id": target_category.pk,
        "branch_id": branch.id,
        "rack_id": target_rack.pk if target_rack else None,
        "has_variants": product.has_variants,
        "compatible_models": product.compatible_models,
        "condition": product.condition,
        "unit": product.unit,
        "tax_treatment": product.tax_treatment,
        "vat_inclusive": product.vat_inclusive,
        "vat_rate": product.vat_rate,
        "supplier_id": target_supplier.pk if target_supplier else None,
        "description": product.description,
        "product_image": product.product_image.name if product.product_image else None,
        "warranty_period_days": product.warranty_period_days,
        "reorder_level": product.reorder_level,
        "is_active": product.is_active,
        "is_deleted": product.is_deleted,
        "deleted_at": product.deleted_at,
        "deleted_by_id": None,
    }

    try:
        with transaction.atomic(using=using):
            if target_product is None:
                target_product = Product.objects.using(using).create(
                    id=product.pk, **product_defaults
                )
            elif not reused_existing_sku:
                for field_name, field_value in product_defaults.items():
                    setattr(target_product, field_name, field_value)
                target_product.save(using=using)
            # When resolving an already-existing destination SKU for transfer/GRN,
            # keep that branch's supplier/rack/catalog metadata untouched.
    except IntegrityError as exc:
        # Handles the race where another request creates the SKU after validation.
        if find_physical_product_by_sku(branch, normalized_sku) is not None:
            raise serializers.ValidationError(
                {
                    "sku": (
                        f"{normalized_sku} already exists in "
                        f"{physical_branch_label(branch)}."
                    )
                }
            ) from exc
        raise

    mirrored_variant_ids = []
    for variant in product.variants.all():
        target_variant = None
        if target_product.pk == product.pk:
            target_variant = (
                ProductVariant.objects.using(using).filter(pk=variant.pk).first()
            )
        if target_variant is None:
            target_variant = resolve_variant_in_physical_database(
                variant, target_product, branch
            )

        variant_defaults = {
            "product_id": target_product.pk,
            "attributes": variant.attributes,
            "available_qty": variant.available_qty,
            "purchase_price": variant.purchase_price,
            "retail_price": variant.retail_price,
            "wholesale_price": variant.wholesale_price,
            "minimum_selling_price": variant.minimum_selling_price,
            "is_base": variant.is_base,
            "is_active": variant.is_active,
        }
        if target_variant is None:
            create_kwargs = dict(variant_defaults)
            if target_product.pk == product.pk:
                create_kwargs["id"] = variant.pk
            target_variant = ProductVariant.objects.using(using).create(**create_kwargs)
        elif not reused_existing_sku:
            for field_name, field_value in variant_defaults.items():
                setattr(target_variant, field_name, field_value)
            target_variant.save(using=using)

        target_rack_ids = []
        for source_rack in variant.racks.all():
            if source_rack.branch_id != branch.id and not strict_racks:
                continue
            mapped = _target_rack(source_rack, branch, using)
            if mapped:
                target_rack_ids.append(mapped.pk)
        target_variant.racks.set(target_rack_ids)
        mirrored_variant_ids.append(target_variant.pk)

    ProductVariant.objects.using(using).filter(product_id=target_product.pk).exclude(
        pk__in=mirrored_variant_ids
    ).delete()
    return target_product
