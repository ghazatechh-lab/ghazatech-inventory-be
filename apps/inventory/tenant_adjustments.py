"""Physical-tenant stock-adjustment create/list endpoints.

This module intentionally does not use the global branch database router.
Every adjustment and corresponding stock/movement record shares one tenant transaction.
"""
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.branches.models import Branch
from apps.branch_data.schema_routing import register_branch_connection
from .models import Product, ProductVariant, ProductStock, StockAdjustment, StockMovement


def _physical_branch(raw):
    try:
        branch = Branch.objects.using('default').get(pk=int(raw), is_active=True)
    except (ValueError, TypeError, Branch.DoesNotExist):
        raise ValidationError({'branch': ['Select an active physical branch.']})
    if branch.tax_mode not in ('VAT', 'NON_VAT'):
        raise ValidationError({'branch': ['Select Sharjah or Dubai, not Consolidated, to adjust stock.']})
    return branch, register_branch_connection(branch.pk, branch.tax_mode)


def _serialize_adjustment(obj, branch, *, product_name='', sku='', variant_label='Base product'):
    return {
        'id': obj.pk, 'adjustment_number': obj.adjustment_number,
        'branch': branch.pk, 'branch_name': branch.branch_name,
        'branch_code': branch.branch_code, 'source_branch_id': branch.pk,
        'source_branch_name': branch.branch_name,
        'product': obj.product_id, 'product_name': product_name, 'sku': sku,
        'variant': obj.variant_id, 'variant_label': variant_label,
        'adjustment_type': obj.adjustment_type, 'quantity': obj.quantity,
        'signed_quantity': (obj.quantity if obj.adjustment_type == 'ADD' else -obj.quantity),
        'reason': obj.reason, 'remarks': obj.remarks, 'status': obj.status,
        'current_quantity': obj.current_quantity,
        'actual_quantity_counted': obj.actual_quantity_counted,
        'quantity_difference': obj.quantity_difference,
        'unit_cost_excluding_vat': str(obj.unit_cost_excluding_vat),
        'value_before': str(obj.value_before), 'value_after': str(obj.value_after),
        'created_at': obj.created_at.isoformat() if obj.created_at else None,
        'updated_at': obj.updated_at.isoformat() if obj.updated_at else None,
        'adjusted_at': obj.created_at.isoformat() if obj.created_at else None,
    }


def create_tenant_adjustment(self, request, *args, **kwargs):
    payload = request.data
    branch, alias = _physical_branch(payload.get('branch') or request.query_params.get('branch') or request.headers.get('X-Branch-ID'))
    try:
        product_id = int(payload.get('product'))
    except (ValueError, TypeError):
        raise ValidationError({'product': ['Choose a product from the selected physical branch.']})
    variant_id = payload.get('variant')
    if variant_id in ('', None, 'null'):
        variant_id = None
    else:
        try:
            variant_id = int(variant_id)
        except (ValueError, TypeError):
            raise ValidationError({'variant': ['Invalid variant.']})
    action = str(payload.get('adjustment_type') or '').upper().strip()
    if action not in ('ADD', 'DEDUCT'):
        raise ValidationError({'adjustment_type': ['Select Increase or Decrease.']})
    try:
        qty = int(payload.get('quantity'))
        if qty <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError({'quantity': ['Enter a positive whole number.']})
    reason = str(payload.get('reason') or '').strip()
    if not reason:
        raise ValidationError({'reason': ['Reason is required.']})
    if len(reason) > 120:
        raise ValidationError({'reason': ['Reason cannot exceed 120 characters.']})
    remarks = str(payload.get('remarks') or '').strip()

    # No lookups use an implicit router, nor do we accept a stock-row ID as a product ID.
    with transaction.atomic(using=alias):
        product = Product.objects.using(alias).filter(
            pk=product_id, branch_id=branch.pk, is_active=True, is_deleted=False,
        ).first()
        if product is None:
            raise ValidationError({'product': [f'Product ID {product_id} does not exist in {branch.branch_name}. Select the actual Product ID, not a stock record ID.']})
        variant = None
        if variant_id is not None:
            variant = ProductVariant.objects.using(alias).filter(
                pk=variant_id, product_id=product.pk, is_active=True,
            ).first()
            if variant is None:
                raise ValidationError({'variant': ['This variant does not belong to the selected product.']})
        if product.has_variants and variant is None:
            raise ValidationError({'variant': ['Select a variant for this product.']})
        stock, _ = ProductStock.objects.using(alias).select_for_update().get_or_create(
            branch_id=branch.pk, product_id=product.pk, variant_id=variant_id,
            warehouse='',
            defaults={'current_stock': 0, 'reserved_stock': 0, 'damaged_stock': 0,
                      'reorder_level': product.reorder_level,
                      'last_stock_update': timezone.now()},
        )
        before = int(stock.current_stock)
        signed = qty if action == 'ADD' else -qty
        after = before + signed
        if signed < 0 and qty > int(stock.available_stock):
            raise ValidationError({'quantity': [f'Only {stock.available_stock} units are available.']})
        if after < 0 or after < int(stock.reserved_stock):
            raise ValidationError({'quantity': ['Insufficient unreserved stock.']})

        # No new purchase cost is supplied by the Adjustment form: retain existing valuation.
        cost = Decimal(str(stock.average_unit_cost or 0))
        cost_excl = Decimal(str(stock.average_unit_cost_excluding_vat or 0))
        adjustment = StockAdjustment.objects.using(alias).create(
            adjustment_number='SA-' + uuid.uuid4().hex[:25].upper(),
            branch_id=branch.pk, product_id=product.pk, variant_id=variant_id,
            adjustment_type=action, quantity=qty, reason=reason, remarks=remarks,
            current_quantity=before, actual_quantity_counted=after,
            quantity_difference=signed, status='APPROVED',
            unit_cost_excluding_vat=cost_excl, vat_treatment='OUT_OF_SCOPE',
            vat_percentage=Decimal('0'), value_before=cost * before,
            value_after=cost * after,
            capitalized_adjustment_value=abs(cost * signed),
            approved_at=timezone.now(),
        )
        stock.current_stock = after
        stock.last_stock_update = timezone.now()
        stock.save(using=alias, update_fields=['current_stock', 'last_stock_update', 'updated_at'])
        StockMovement.objects.using(alias).create(
            movement_number='SM-' + uuid.uuid4().hex[:25].upper(),
            branch_id=branch.pk, product_id=product.pk, variant_id=variant_id,
            movement_type='ADJUSTMENT', quantity=signed,
            previous_stock=before, new_stock=after,
            quantity_before=before, quantity_after=after,
            reference_type='STOCK_ADJUSTMENT', reference_id=str(adjustment.pk),
            remarks=(reason + '. ' + remarks).strip(),
            unit_cost_excluding_vat=cost_excl, vat_treatment='OUT_OF_SCOPE',
            vat_percentage=Decimal('0'), capitalized_unit_cost=cost,
            net_value_change=cost * signed, gross_value_change=cost * signed,
            running_stock_value=cost * after,
        )
    result = _serialize_adjustment(adjustment, branch, product_name=product.product_name, sku=product.sku)
    return Response({'success': True, 'message': 'Stock adjustment recorded', 'data': result}, status=201)


def list_tenant_adjustments(self, request, *args, **kwargs):
    raw = request.query_params.get('branch') or request.headers.get('X-Branch-ID')
    if raw:
        try:
            selected = Branch.objects.using('default').get(pk=int(raw))
        except (Branch.DoesNotExist, TypeError, ValueError):
            raise ValidationError({'branch': ['Invalid branch.']})
        if selected.tax_mode in ('VAT', 'NON_VAT'):
            branches = [selected]
        else:
            branches = list(Branch.objects.using('default').filter(is_active=True, tax_mode__in=['VAT', 'NON_VAT']))
    else:
        branches = list(Branch.objects.using('default').filter(is_active=True, tax_mode__in=['VAT', 'NON_VAT']))
    rows = []
    for branch in branches:
        alias = register_branch_connection(branch.pk, branch.tax_mode)
        queryset = StockAdjustment.objects.using(alias).filter(branch_id=branch.pk).order_by('-created_at')
        for key in ('adjustment_type', 'status'):
            value = request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{key: value})
        for entry in queryset:
            product = Product.objects.using(alias).filter(pk=entry.product_id).values('product_name','sku').first() or {}
            variant = (ProductVariant.objects.using(alias).filter(pk=entry.variant_id).first()
                       if entry.variant_id else None)
            label = ' / '.join(str(v) for v in (variant.attributes or {}).values()) if variant else 'Base product'
            rows.append(_serialize_adjustment(entry, branch, product_name=product.get('product_name',''),
                        sku=product.get('sku',''), variant_label=label or 'Base product'))
    rows.sort(key=lambda r: r['created_at'] or '', reverse=True)
    page = self.paginate_queryset(rows)
    if page is not None:
        return self.get_paginated_response(page)
    return Response({'success': True, 'data': rows})
