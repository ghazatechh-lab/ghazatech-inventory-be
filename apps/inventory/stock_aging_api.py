"""Read-only, tenant-scoped stock aging report.

Aging is reconstructed from recorded signed stock movements using FIFO. When
movement history cannot reconcile to current stock, age is unknown rather than
an invented receipt date. Does not modify stock or book clearance transactions.
"""
from collections import defaultdict, deque
from datetime import timedelta

from django.db import connections
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from apps.branches.models import Branch
from apps.branch_data.schema_routing import register_branch_connection
from .models import ProductStock, StockMovement, RackStockAllocation


def _movement_ages(alias, branch_id, now):
    movements = StockMovement.objects.using(alias).filter(branch_id=branch_id).order_by('created_at', 'pk').values(
        'product_id', 'variant_id', 'warehouse', 'quantity', 'movement_type', 'created_at'
    )
    grouped = defaultdict(list)
    sales = defaultdict(int)
    cutoff = now - timedelta(days=90)
    for m in movements.iterator(chunk_size=2000):
        key = (m['product_id'], m['variant_id'], m['warehouse'] or '')
        grouped[key].append(m)
        if m['movement_type'] == 'SALE' and m['created_at'] >= cutoff:
            sales[key] += abs(min(0, int(m['quantity'])))
    return grouped, sales


def _stock_age(events, current, now):
    """FIFO oldest surviving unit, if entire current stock can be explained."""
    layers = deque()
    for event in events:
        q = int(event['quantity'])
        if q > 0:
            layers.append([q, event['created_at']])
        elif q < 0:
            remove = -q
            while remove > 0 and layers:
                take = min(remove, layers[0][0])
                layers[0][0] -= take
                remove -= take
                if layers[0][0] == 0:
                    layers.popleft()
            if remove:
                return None
    if current <= 0:
        return None
    if sum(row[0] for row in layers) != current:
        return None
    return max(0, (now.date() - layers[0][1].date()).days) if layers else None


def _one_branch(branch, now):
    alias = register_branch_connection(branch.pk, branch.tax_mode)
    expected = f'branch_{branch.pk:08d}'
    with connections[alias].cursor() as cursor:
        cursor.execute('SELECT current_schema()')
        if cursor.fetchone()[0] != expected:
            raise RuntimeError('Tenant schema mismatch for branch %s' % branch.pk)
    grouped, sales = _movement_ages(alias, branch.pk, now)
    stocks = (ProductStock.objects.using(alias).filter(branch_id=branch.pk, current_stock__gt=0)
              .select_related('product', 'variant').order_by('pk'))
    rows = []
    for stock in stocks.iterator(chunk_size=250):
        product = stock.product
        if getattr(product, 'is_deleted', False):
            continue
        key = (stock.product_id, stock.variant_id, stock.warehouse or '')
        current = int(stock.current_stock)
        available = max(0, current - int(stock.reserved_stock))
        age = _stock_age(grouped[key], current, now)
        sold = sales[key]
        minimum = int(stock.reorder_level)
        # Velocity target is a planning *estimate*, not a configured max-stock level.
        target = max(minimum, sold * 2) if minimum or sold else None
        is_over = target is not None and current > target
        is_slow = age is not None and age > 90 and sold < 5
        if is_over:
            label, action = 'Overstock', 'Review Stock'
        elif is_slow:
            label, action = 'Slow Moving', 'Consider Clearance'
        else:
            label, action = 'Normal', 'Keep Stock'
        if age is None:
            bucket = 'Unknown'
        elif age <= 30:
            bucket = '0–30'
        elif age <= 60:
            bucket = '31–60'
        elif age <= 90:
            bucket = '61–90'
        elif age <= 180:
            bucket = '91–180'
        else:
            bucket = '180+'
        racks = list(RackStockAllocation.objects.using(alias).filter(stock_id=stock.pk).select_related('rack').values_list('rack__rack_code', flat=True))
        if not racks and stock.variant_id:
            racks = list(stock.variant.racks.using(alias).values_list('rack_code', flat=True))
        if not racks and product.rack_id:
            racks = [product.rack.rack_code] if product.rack_id else []
        rows.append({
            'id': f'{branch.branch_code}:{stock.pk}', 'product_id': stock.product_id,
            'branch_id': branch.pk, 'branch_code': branch.branch_code, 'branch_name': branch.branch_name,
            'name': product.product_name, 'sku': product.sku,
            'variant': stock.variant.attributes if stock.variant_id else {},
            'warehouse': stock.warehouse or '—', 'racks': racks,
            'quantity': current, 'available': available, 'reserved': int(stock.reserved_stock),
            'age_days': age, 'age_bucket': bucket, 'sales_90d': sold,
            'reorder_level': minimum, 'estimated_target': target,
            'status': label, 'suggested_action': action,
            'stock_value': round(float(stock.average_unit_cost) * current, 2),
        })
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stock_aging_report(request):
    branches = Branch.objects.using('default').filter(is_active=True, tax_mode__in=['VAT', 'NON_VAT'])
    branch_map = {str(b.pk): b for b in branches}
    branch_map.update({b.branch_code.upper(): b for b in branches})
    selected = str(request.query_params.get('branch') or request.headers.get('X-Branch-ID') or '').strip()
    if not selected and getattr(request.user, 'is_superuser', False):
        selected = 'CONSOLIDATED'
    if not selected:
        return Response({'detail': 'Select a branch or Consolidated workspace.'}, status=status.HTTP_400_BAD_REQUEST)
    requested = Branch.objects.using('default').filter(pk=int(selected)).first() if selected.isdigit() else Branch.objects.using('default').filter(branch_code__iexact=selected).first()
    if requested is None or not requested.is_active:
        return Response({'detail': 'Unknown or inactive branch.'}, status=status.HTTP_400_BAD_REQUEST)
    allowed_codes = set(getattr(request.user, 'permission_codes', []) or [])
    can_all = bool(request.user.is_superuser or '*' in allowed_codes or 'branches.view_all' in allowed_codes)
    user_branch_id = getattr(request.user, 'branch_id', None)
    if not can_all and requested.pk != user_branch_id:
        return Response({'detail': 'Branch access denied.'}, status=status.HTTP_403_FORBIDDEN)
    if requested.tax_mode in ('VAT', 'NON_VAT'):
        targets = [requested]
    elif requested.branch_code.upper() == 'CONSOLIDATED':
        targets = list(branches.order_by('pk'))
    else:
        return Response({'detail': 'Unsupported branch selection.'}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    rows = []
    for branch in targets:
        try:
            rows.extend(_one_branch(branch, now))
        except Exception:
            # Fail rather than returning a misleading partial consolidated report.
            raise
    return Response({'results': rows, 'count': len(rows), 'age_method': 'FIFO stock movements; unknown when history is incomplete',
                     'overstock_method': 'Estimated target = max(reorder level, two times sales in 90 days)'})
