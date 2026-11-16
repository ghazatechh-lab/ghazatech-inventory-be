"""Production rack allocation recovery for GhazaTech.
Run inside Django shell: exec(open('/tmp/repair_rack_allocations.py').read())
RACK_REPAIR_MODE=export|preview|apply; RACK_REPAIR_CSV=/tmp/rack_mapping.csv
"""
import csv
import os
from collections import Counter
from pathlib import Path
from django.db import transaction
from apps.branches.models import Branch
from apps.branch_data.schema_routing import register_branch_connection
from apps.inventory.models import ProductStock, Rack, RackStockAllocation

MODE = os.environ.get('RACK_REPAIR_MODE', 'export').strip().lower()
PATH = Path(os.environ.get('RACK_REPAIR_CSV', '/tmp/rack_mapping.csv'))
FIELDS = ['branch_code','stock_id','product_id','sku','product_name','variant_id','warehouse','current_stock','rack_code','available_racks']
if MODE not in ('export', 'preview', 'apply'):
    raise RuntimeError('RACK_REPAIR_MODE must be export, preview or apply')
branches = {b.branch_code: b for b in Branch.objects.using('default').filter(is_active=True, tax_mode__in=('VAT','NON_VAT'))}

if MODE == 'export':
    if PATH.exists():
        raise RuntimeError(f'{PATH} exists. Choose a new file path to prevent overwriting your mapping.')
    rows=[]
    for code, branch in sorted(branches.items()):
        alias=register_branch_connection(branch.pk, branch.tax_mode)
        racks=list(Rack.objects.using(alias).filter(branch_id=branch.pk,is_active=True).order_by('rack_code').values_list('rack_code',flat=True))
        for stock in ProductStock.objects.using(alias).filter(branch_id=branch.pk).select_related('product').order_by('pk').iterator():
            existing=list(RackStockAllocation.objects.using(alias).filter(stock_id=stock.pk).values_list('rack_id','quantity'))
            if existing:
                continue
            rows.append({'branch_code':code,'stock_id':stock.pk,'product_id':stock.product_id,
                         'sku':stock.product.sku,'product_name':stock.product.product_name,
                         'variant_id':stock.variant_id or '', 'warehouse':stock.warehouse,
                         'current_stock':stock.current_stock,
                         'rack_code':racks[0] if len(racks)==1 else '',
                         'available_racks':', '.join(racks)})
    with PATH.open('w',newline='',encoding='utf-8-sig') as f:
        out=csv.DictWriter(f,fieldnames=FIELDS);out.writeheader();out.writerows(rows)
    print(f'EXPORTED {len(rows)} unallocated stock records to {PATH}')
    for code,count in sorted(Counter(r['branch_code'] for r in rows).items()):
        print(f'{code}: {count} records; single-rack branch entries prefilled where safe')
    print('Fill rack_code for every product using the physically correct branch rack; leave unknown locations blank.')
else:
    if not PATH.is_file():
        raise RuntimeError(f'Mapping not found: {PATH}')
    with PATH.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise RuntimeError('CSV header is incomplete')
        rows=list(reader)
    seen=set();errors=[];planned=[];skipped=Counter()
    for line,row in enumerate(rows,2):
        code=row['branch_code'].strip(); rack_code=row['rack_code'].strip(); stock_str=row['stock_id'].strip()
        key=(code,stock_str)
        if key in seen:
            errors.append(f'line {line}: repeated stock {key}');continue
        seen.add(key)
        if not rack_code:
            skipped['no rack selected']+=1;continue
        branch=branches.get(code)
        if not branch:
            errors.append(f'line {line}: unknown branch {code}');continue
        alias=register_branch_connection(branch.pk,branch.tax_mode)
        try: stock_id=int(stock_str); old_quantity=int(row['current_stock'])
        except ValueError:
            errors.append(f'line {line}: invalid stock ID/quantity');continue
        stock=ProductStock.objects.using(alias).filter(pk=stock_id,branch_id=branch.pk).first()
        if not stock:
            errors.append(f'line {line}: stock not found in {code}: {stock_id}');continue
        if (str(stock.product_id)!=row['product_id'].strip() or
            str(stock.variant_id or '')!=row['variant_id'].strip() or
            stock.current_stock!=old_quantity):
            errors.append(f'line {line}: stock identity or current_stock changed for {code} {stock_id}; re-export');continue
        rack=Rack.objects.using(alias).filter(branch_id=branch.pk,rack_code=rack_code,is_active=True).first()
        if rack is None:
            errors.append(f'line {line}: rack {rack_code!r} not active in {code}');continue
        existing=list(RackStockAllocation.objects.using(alias).filter(stock_id=stock_id))
        if existing:
            if len(existing)==1 and existing[0].rack_id==rack.pk and existing[0].quantity==stock.current_stock:
                skipped['already correct']+=1;continue
            errors.append(f'line {line}: existing rack allocation differs for {code} stock {stock_id}; resolve manually');continue
        planned.append((code,alias,branch.pk,stock_id,stock.product_id,stock.variant_id,rack.pk,rack_code,old_quantity))
    print('MODE:',MODE.upper())
    for item in planned:
        code,_,__,sid,pid,vid,rid,rack_code,qty=item
        print(f'{code} stock={sid} product={pid} variant={vid or "base"} rack={rack_code} quantity={qty}')
    print('Planned:',len(planned),'Skipped:',dict(skipped),'Errors:',len(errors))
    for error in errors: print('ERROR:',error)
    if errors:
        raise RuntimeError('Errors found; nothing applied. Correct CSV and re-preview.')
    if MODE=='apply':
        # One transaction per tenant, with row locking and a fresh consistency check.
        by_alias={}
        for item in planned: by_alias.setdefault(item[1],[]).append(item)
        for alias,items in by_alias.items():
            with transaction.atomic(using=alias):
                for code,_,branch_id,sid,pid,vid,rid,rack_code,qty in items:
                    stock=ProductStock.objects.using(alias).select_for_update().get(pk=sid,branch_id=branch_id)
                    if (stock.product_id!=pid or stock.variant_id!=vid or stock.current_stock!=qty):
                        raise RuntimeError(f'Stock {code}/{sid} changed; transaction rolled back')
                    if not Rack.objects.using(alias).filter(pk=rid,branch_id=branch_id,is_active=True).exists():
                        raise RuntimeError(f'Rack {rack_code} changed; transaction rolled back')
                    if RackStockAllocation.objects.using(alias).filter(stock_id=sid).exists():
                        raise RuntimeError(f'Allocation {code}/{sid} changed; transaction rolled back')
                    RackStockAllocation.objects.using(alias).create(stock_id=sid,rack_id=rid,quantity=qty)
            print(f'COMMITTED {len(items)} allocations to {alias}')
        print('DONE. ProductStock.current_stock was not modified.')
    else:
        print('DRY RUN: no database changes.')
