"""Reconcile demo catalog visibility and seed brands/racks safely.
Run ONLY on dev/demo. Does not delete or move stock, and never modifies non-DEMO products.
"""
import os
from django.db import transaction
from apps.branches.models import Branch
from apps.inventory.models import Brand, Category, Rack, Product, ProductStock

if os.environ.get('CONFIRM_TEST_SEED') != 'YES':
    raise RuntimeError('Pass -e CONFIRM_TEST_SEED=YES')

BRANCHES = (('BR01','vat'), ('BR02','non_vat'))
rack_specs = [('DEMO-A01','Accessories'), ('DEMO-S01','Storage'), ('DEMO-M01','Memory'), ('DEMO-P01','Parts'), ('DEMO-O01','Other')]
master_branches = {b.branch_code:b for b in Branch.objects.using('default').filter(branch_code__in=['BR01','BR02','BR03'])}
if 'BR01' not in master_branches or 'BR02' not in master_branches:
    raise RuntimeError('Missing BR01/BR02 in default database')

# Gather all demo products from each physical database before writing anything.
source = {}
for code,alias in BRANCHES:
    branch = master_branches[code]
    physical = Branch.objects.using(alias).filter(pk=branch.pk,branch_code=code).first()
    if physical is None:
        raise RuntimeError(f'{alias}: mirrored branch id missing or mismatched')
    rows = list(Product.objects.using(alias).filter(branch_id=branch.pk,sku__contains='DEMO-').select_related('brand','category'))
    source[alias] = rows
    print(f'{code} physical demo products={len(rows)}, stocks={ProductStock.objects.using(alias).filter(branch_id=branch.pk,product_id__in=[p.pk for p in rows]).count()}')

# Shared catalog: the project's inventory router selects DEFAULT for Product/Brand/Category/Rack.
with transaction.atomic(using='default'):
    for code,alias in BRANCHES:
        branch = master_branches[code]
        rack_map = {}
        for rack_code,rack_label in rack_specs:
            rack,_=Rack.objects.using('default').get_or_create(branch_id=branch.pk,rack_code=rack_code,defaults={'rack_name':f'Demo {rack_label}', 'is_active':True})
            rack_map[rack_label]=rack
        for old in source[alias]:
            brand,_=Brand.objects.using('default').get_or_create(name=old.brand.name)
            category,_=Category.objects.using('default').get_or_create(name=old.category.name)
            rack = rack_map.get(old.category.name, rack_map['Other'])
            defaults={
                'product_name':old.product_name,
                'brand_id':brand.pk,'category_id':category.pk,
                'condition':old.condition,'tax_treatment':old.tax_treatment,
                'rack_id':rack.pk,'reorder_level':old.reorder_level,
            }
            item,created=Product.objects.using('default').get_or_create(
                branch_id=branch.pk,sku=old.sku,defaults=defaults)
            if not created and item.rack_id is None:
                item.rack_id=rack.pk
                item.save(using='default',update_fields=['rack'])
    print('Shared default catalog: demo products:',Product.objects.using('default').filter(sku__contains='DEMO-').count())

# Physical DB racks and brand/category reference data. Do not overwrite any product/stock PKs.
for code,alias in BRANCHES:
    branch = master_branches[code]
    with transaction.atomic(using=alias):
        local_racks={}
        for rack_code,rack_label in rack_specs:
            rack,_=Rack.objects.using(alias).get_or_create(branch_id=branch.pk,rack_code=rack_code,defaults={'rack_name':f'Demo {rack_label}','is_active':True})
            local_racks[rack_label]=rack
        for item in source[alias]:
            if item.rack_id is None:
                cat=Category.objects.using(alias).get(pk=item.category_id)
                item.rack_id=local_racks.get(cat.name,local_racks['Other']).pk
                item.save(using=alias,update_fields=['rack'])
    print(f'{code}: racks={Rack.objects.using(alias).filter(branch_id=branch.pk).count()}, products={Product.objects.using(alias).filter(branch_id=branch.pk).count()}')

print('Finished: no existing products or stock deleted. IMPORTANT: default and physical product primary keys can differ; verify UI stock linkage before treating combined stock numbers as accurate.')
