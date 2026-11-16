"""Rack allocation mutations. Call within transaction.atomic(using=alias).

ProductStock owns the physical balance. RackStockAllocation is only its location
breakdown. Legacy unallocated balances must first be assigned to a rack.
"""
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from .models import Rack, RackStockAllocation


def rack_for_branch(alias, branch_id, rack_id):
    rack = Rack.objects.using(alias).filter(
        pk=rack_id, branch_id=branch_id, is_active=True
    ).first()
    if not rack:
        raise ValidationError({'rack': ['Select an active rack belonging to this physical branch.']})
    return rack


def apply_rack_delta(alias, stock, rack_id, delta, *, new_total):
    """Mutate a single rack, checking allocation capacity and available rack stock.

    Use a stock-row SELECT FOR UPDATE in the caller to serialize concurrent writes.
    This deliberately doesn't infer a rack for previously unallocated quantities.
    """
    rack = rack_for_branch(alias, stock.branch_id, rack_id)
    existing = RackStockAllocation.objects.using(alias).filter(
        stock_id=stock.pk, rack_id=rack.pk
    ).first()
    before = int(existing.quantity) if existing else 0
    after = before + int(delta)
    if after < 0:
        raise ValidationError({'rack': [f'{rack.rack_code} contains {before} units; cannot remove {abs(delta)}. Allocate legacy unassigned stock first if necessary.']})
    assigned = RackStockAllocation.objects.using(alias).filter(stock_id=stock.pk).aggregate(
        total=Sum('quantity')
    )['total'] or 0
    if assigned + int(delta) > int(new_total):
        raise ValidationError({'rack': ['Rack allocation exceeds total physical stock. Check unallocated stock and existing rack balances.']})
    if existing:
        existing.quantity = after
        existing.save(using=alias, update_fields=['quantity', 'updated_at'])
    elif after > 0:
        RackStockAllocation.objects.using(alias).create(
            stock_id=stock.pk, rack_id=rack.pk, quantity=after
        )
    return rack


def validate_rack_quantity(requested_quantity, other_racks_quantity, physical_quantity):
    """Check an absolute rack balance against the fixed physical stock total.

    Allocating stock to a rack must never create new stock or ledger movements.
    """
    requested = int(requested_quantity)
    others = int(other_racks_quantity)
    physical = int(physical_quantity)
    if requested < 0 or others < 0 or physical < 0:
        raise ValidationError({'quantity': ['Stock quantities cannot be negative.']})
    if requested + others > physical:
        available = max(0, physical - others)
        raise ValidationError({'quantity': [
            f'Only {available} units can be assigned to this rack. '
            'Move quantities from other racks first, or record an actual stock receipt.'
        ]})
    return physical - requested - others
