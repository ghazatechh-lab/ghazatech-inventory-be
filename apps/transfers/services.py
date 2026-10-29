"""Tenant-safe Stock Transfer operations for schema-isolated branches.

Default DB owns workflow state; tenant DBs own balances/movements. We cannot
atomically commit two PostgreSQL databases. Each tenant movement therefore has
an idempotency key so retry can finish an interrupted operation safely.
"""
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.branch_data.schema_routing import register_branch_connection
from apps.inventory.models import (Brand, Category, Product, ProductVariant,
                                   ProductStock, StockMovement)
from .models import StockTransfer, StockTransferItem


def _alias(branch):
    return register_branch_connection(branch.pk, branch.tax_mode)


def _key(t, item, direction):
    return f"xfer:{t.pk}:item:{item.pk}:{direction}"


def _ensure_source(t, item, alias):
    pk = item.source_product_id or item.product_id
    product = Product.objects.using(alias).filter(pk=pk, branch_id=t.from_branch_id,
                       is_active=True, is_deleted=False).first()
    if not product:
        raise serializers.ValidationError({"items": f"Source product {pk} unavailable in {t.from_branch.branch_name}."})
    vpk = item.source_variant_id or item.variant_id
    variant = None
    if vpk:
        variant = ProductVariant.objects.using(alias).filter(pk=vpk, product_id=product.pk).first()
        if not variant:
            raise serializers.ValidationError({"items": f"Source variant {vpk} not found."})
    return product, variant


def _stock_variant(variant):
    # Base variants are recorded in stock with variant_id=NULL by this ERP.
    return None if variant is None or variant.is_base else variant.pk


def _move(*, alias, branch_id, product, variant, quantity, movement_type,
          warehouse, key, transfer_number, unit_cost, actor_id):
    """Lock and mutate one tenant stock row, with idempotent movement lookup.

    Called inside transaction.atomic(using=alias), under the default transfer
    row lock. The reference key is specific to a transfer item and direction.
    """
    existing = StockMovement.objects.using(alias).filter(
        reference_type="Transfer", reference_id=key, movement_type=movement_type
    ).first()
    if existing:
        if (existing.product_id != product.pk or existing.branch_id != branch_id
                or existing.quantity != quantity):
            raise serializers.ValidationError({"items": "Transfer movement key conflict; manual review required."})
        return existing

    stock, _ = ProductStock.objects.using(alias).select_for_update().get_or_create(
        branch_id=branch_id, product_id=product.pk,
        variant_id=_stock_variant(variant), warehouse=warehouse,
        defaults={"current_stock": 0, "reserved_stock": 0,
                  "reorder_level": product.reorder_level},
    )
    before = int(stock.current_stock or 0)
    after = before + quantity
    if after < int(stock.reserved_stock or 0):
        raise serializers.ValidationError({"items": f"Insufficient unreserved stock for {product.sku}. Available {stock.available_stock}."})
    if after < 0:
        raise serializers.ValidationError({"items": f"Insufficient stock for {product.sku}."})
    cost = Decimal(str(unit_cost or 0))
    if quantity > 0:
        old_cost = Decimal(str(stock.average_unit_cost or 0))
        stock.average_unit_cost = ((Decimal(before)*old_cost + Decimal(quantity)*cost)/Decimal(after)).quantize(Decimal("0.0001")) if after else cost
        stock.average_unit_cost_excluding_vat = cost
        stock.last_purchase_cost_excluding_vat = cost
        stock.last_purchase_cost = cost
        stock.last_tax_treatment = "NON_VAT"
        stock.last_vat_percentage = 0
        stock.valuation_updated_at = timezone.now()
    stock.current_stock = after
    stock.last_stock_update = timezone.now()
    stock.save(using=alias)
    return StockMovement.objects.using(alias).create(
        movement_number=f"SM-XF-{uuid4().hex[:24].upper()}",
        product_id=product.pk, variant_id=_stock_variant(variant),
        branch_id=branch_id, movement_type=movement_type,
        warehouse=warehouse, quantity=quantity,
        previous_stock=before, new_stock=after,
        quantity_before=before, quantity_after=after,
        reference_type="Transfer", reference_id=key,
        remarks=f"{transfer_number}; shared actor ID {actor_id}",
        performed_by_id=None, unit_cost_excluding_vat=cost,
        capitalized_unit_cost=cost,
        net_value_change=Decimal(quantity)*cost,
        gross_value_change=Decimal(quantity)*cost,
        running_stock_value=Decimal(after)*stock.average_unit_cost,
        vat_treatment="OUT_OF_SCOPE", vat_percentage=0,
        source_document_type="Transfer", source_document_number=transfer_number,
    )


def _destination_product(source_product, destination_branch, destination_alias):
    """Find by stable SKU, not by source DB numeric primary key."""
    product = Product.objects.using(destination_alias).filter(
        branch_id=destination_branch.pk, sku__iexact=source_product.sku,
        is_deleted=False).first()
    # TRANSFER_IMAGE_SYNC: images are shared media files; do not copy DB-local IDs.
    source_image_name = (getattr(source_product.product_image, "name", None) or "").strip()
    if source_image_name:
        storage = source_product.product_image.storage
        # Check the referenced file before storing its name in a different tenant DB.
        if not storage.exists(source_image_name):
            source_image_name = ""
    if product:
        if not product.is_active:
            raise serializers.ValidationError({"items": f"Destination SKU {source_product.sku} is inactive."})
        if source_image_name and not product.product_image:
            Product.objects.using(destination_alias).filter(pk=product.pk).update(
                product_image=source_image_name
            )
            product.product_image.name = source_image_name
        return product
    source_alias = source_product._state.db
    brand_name = Brand.objects.using(source_alias).get(pk=source_product.brand_id).name
    cat_name = Category.objects.using(source_alias).get(pk=source_product.category_id).name
    brand, _ = Brand.objects.using(destination_alias).get_or_create(name=brand_name)
    category, _ = Category.objects.using(destination_alias).get_or_create(name=cat_name)
    # Avoid cross-tenant barcode collisions; SKU is stable transfer identity.
    barcode = source_product.barcode
    if barcode and Product.objects.using(destination_alias).filter(
            branch_id=destination_branch.pk, barcode=barcode).exists():
        barcode = None
    return Product.objects.using(destination_alias).create(
        product_name=source_product.product_name, sku=source_product.sku,
        barcode=barcode, brand_id=brand.pk, category_id=category.pk,
        branch_id=destination_branch.pk, rack_id=None, supplier_id=None,
        has_variants=source_product.has_variants,
        compatible_models=source_product.compatible_models,
        condition=source_product.condition, unit=source_product.unit,
        tax_treatment=("VAT" if destination_branch.tax_mode == "VAT" else "NON_VAT"),
        vat_inclusive=(destination_branch.tax_mode == "VAT"),
        vat_rate=(5 if destination_branch.tax_mode == "VAT" else 0),
        description=source_product.description,
        product_image=source_image_name or None,
        warranty_period_days=source_product.warranty_period_days,
        reorder_level=source_product.reorder_level, is_active=True,
    )


def _destination_variant(source_variant, dest_product, alias):
    if source_variant is None:
        return None
    found = ProductVariant.objects.using(alias).filter(
        product_id=dest_product.pk, attributes=source_variant.attributes,
        is_base=source_variant.is_base).first()
    if found:
        return found
    return ProductVariant.objects.using(alias).create(
        product_id=dest_product.pk, attributes=source_variant.attributes,
        is_base=source_variant.is_base, is_active=True,
        purchase_price=source_variant.purchase_price,
        retail_price=source_variant.retail_price,
        wholesale_price=source_variant.wholesale_price,
        minimum_selling_price=source_variant.minimum_selling_price,
    )


def dispatch(t, u):
    with transaction.atomic(using="default"):
        t = StockTransfer.objects.using("default").select_for_update().select_related(
            "from_branch", "to_branch").get(pk=t.pk)
        if t.status not in ("APPROVED", "IN_TRANSIT"):
            raise serializers.ValidationError({"status": "Only approved transfers can dispatch."})
        alias = _alias(t.from_branch)
        items = list(StockTransferItem.objects.using("default").filter(transfer_id=t.pk))
        if not items:
            raise serializers.ValidationError({"items": "Transfer has no items."})
        with transaction.atomic(using=alias):
            for item in items:
                source, variant = _ensure_source(t, item, alias)
                qty = int(item.dispatched_quantity or item.requested_quantity or 0)
                if qty <= 0:
                    raise serializers.ValidationError({"items": "Quantity must be positive."})
                # A single warehouse is required to avoid partial dispatch
                # across warehouse rows without an explicit allocation ledger.
                rows = list(ProductStock.objects.using(alias).filter(
                    branch_id=t.from_branch_id, product_id=source.pk,
                    variant_id=_stock_variant(variant)))
                eligible = [s for s in rows if s.available_stock >= qty]
                if not eligible and not StockMovement.objects.using(alias).filter(
                    reference_type="Transfer", reference_id=_key(t,item,"out"),
                    movement_type="TRANSFER_OUT").exists():
                    raise serializers.ValidationError({"items": f"{source.sku}: insufficient stock in a single warehouse."})
                warehouse = (eligible[0].warehouse if eligible else
                    StockMovement.objects.using(alias).get(reference_id=_key(t,item,"out"),
                        movement_type="TRANSFER_OUT").warehouse)
                _move(alias=alias, branch_id=t.from_branch_id,
                    product=source, variant=variant, quantity=-qty,
                    movement_type="TRANSFER_OUT", warehouse=warehouse,
                    key=_key(t,item,"out"), transfer_number=t.transfer_number,
                    unit_cost=item.transfer_unit_cost, actor_id=u.pk)
        for item in items:
            item.dispatched_quantity = int(item.dispatched_quantity or item.requested_quantity)
            item.save(using="default", update_fields=["dispatched_quantity"])
        t.status = "IN_TRANSIT"
        t.dispatched_by = u
        t.dispatch_date = timezone.localdate()
        t.dispatched_at = t.dispatched_at or timezone.now()
        t.save(using="default", update_fields=["status", "dispatched_by", "dispatch_date", "dispatched_at", "updated_at"])
        return t


def receive(t, u):
    with transaction.atomic(using="default"):
        t = StockTransfer.objects.using("default").select_for_update().select_related(
            "from_branch", "to_branch").get(pk=t.pk)
        if t.status not in ("IN_TRANSIT", "RECEIVED"):
            raise serializers.ValidationError({"status": "Only dispatched transfers can be received."})
        src_alias = _alias(t.from_branch)
        dst_alias = _alias(t.to_branch)
        items = list(StockTransferItem.objects.using("default").filter(transfer_id=t.pk))
        with transaction.atomic(using=dst_alias):
            for item in items:
                qty = int(item.dispatched_quantity or 0)
                if qty <= 0:
                    raise serializers.ValidationError({"items": "Item has not been dispatched."})
                if not StockMovement.objects.using(src_alias).filter(
                        reference_type="Transfer", reference_id=_key(t,item,"out"),
                        movement_type="TRANSFER_OUT", quantity=-qty).exists():
                    raise serializers.ValidationError({"items": "Source dispatch movement missing; manual review required."})
                source, variant = _ensure_source(t, item, src_alias)
                dest = _destination_product(source, t.to_branch, dst_alias)
                dest_variant = _destination_variant(variant, dest, dst_alias)
                _move(alias=dst_alias, branch_id=t.to_branch_id, product=dest,
                      variant=dest_variant, quantity=qty, movement_type="TRANSFER_IN",
                      warehouse="", key=_key(t,item,"in"),
                      transfer_number=t.transfer_number,
                      unit_cost=item.transfer_unit_cost, actor_id=u.pk)
        total = Decimal("0")
        for item in items:
            qty = int(item.dispatched_quantity or 0)
            item.received_quantity = qty
            item.destination_value = Decimal(qty)*item.transfer_unit_cost
            item.value_difference = item.destination_value - item.source_value
            item.save(using="default", update_fields=["received_quantity", "destination_value", "value_difference"])
            total += item.destination_value
        t.status = "RECEIVED"
        t.received_by = u
        t.received_date = timezone.localdate()
        t.received_at = t.received_at or timezone.now()
        t.destination_stock_value = total
        t.value_difference = total - Decimal(t.source_stock_value or 0)
        t.reconciliation_status = "MATCHED" if t.value_difference == 0 else "VARIANCE"
        t.save(using="default", update_fields=["status", "received_by", "received_date", "received_at",
                   "destination_stock_value", "value_difference", "reconciliation_status", "updated_at"])
        return t
