"""Add extra demo employees/payroll and physical-branch inventory without deleting records.
Run with CONFIRM_TEST_SEED=YES via manage.py shell < this file.
For non-production development/test databases only.
"""
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from django.db import transaction, connections
from django.db.models import Sum
from apps.branches.models import Branch
from apps.hrms.models import Designation, Employee, PayrollRun, PayrollEntry
from apps.inventory.models import Brand, Category, Product, ProductStock

if os.getenv('CONFIRM_TEST_SEED') != 'YES':
    raise RuntimeError('Set CONFIRM_TEST_SEED=YES to insert demo data.')
D = lambda n: Decimal(str(n))
branch_by_code = {b.branch_code:b for b in Branch.objects.using('default').filter(branch_code__in=['BR01','BR02'])}
if len(branch_by_code) != 2:
    raise RuntimeError('BR01 and BR02 must already exist in default database. Run initial seed first.')

people = [
  ('Irfan','Basheer','Technician','BR01',3600,450),
  ('Anjali','Prasad','Sales Executive','BR01',3900,600),
  ('Bilal','Hameed','Storekeeper','BR01',3100,350),
  ('Meera','Krishnan','Accountant','BR01',4700,850),
  ('Junaid','Farhan','Service Engineer','BR01',5200,1000),
  ('Kavya','Nair','Receptionist','BR02',3000,450),
  ('Salman','Rasheed','Driver','BR02',2900,350),
  ('Riya','Thomas','HR Executive','BR02',4300,700),
  ('Faizal','Latheef','Supervisor','BR02',4900,800),
  ('Deepak','Raj','IT Support','BR02',4100,650),
]

with transaction.atomic(using='default'):
    employees=[]
    for index,(first,last,role,code,basic,allow) in enumerate(people,11):
        designation,_ = Designation.objects.using('default').get_or_create(name=role,defaults={'designation_name':role})
        emp,_ = Employee.objects.using('default').get_or_create(
            employee_code=f'DEMO-EMP-{index:03}',
            defaults=dict(first_name=first,last_name=last,designation=designation,branch=branch_by_code[code],
                          joining_date=date(2026,1,1),basic_salary=D(basic),allowances=D(allow),
                          employment_status='ACTIVE',employment_type='FULL_TIME',is_active=True))
        employees.append(emp)
    # Separate October payroll runs; September back-history for these new employees too.
    for code in ['BR01','BR02']:
        branch=branch_by_code[code]
        for yr,mo in [(2026,7),(2026,8),(2026,9)]:
            period=f'{yr}-{mo:02}'
            run,_=PayrollRun.objects.using('default').get_or_create(
                branch=branch,period=period,salary_type='REGULAR',
                defaults=dict(payroll_date=date(yr,mo,28),status='COMPLETED'))
            for index,emp in enumerate(employees,11):
                if emp.branch_id != branch.pk:
                    continue
                gross=D(emp.basic_salary or 0)+D(emp.allowances or 0)
                deduction=D(120+index*10)
                paid=mo in (7,8)
                PayrollEntry.objects.using('default').get_or_create(
                    employee=emp,period=period,salary_type='REGULAR',
                    defaults=dict(payroll_run=run,branch=branch,payroll_date=date(yr,mo,28),
                    basic_salary=emp.basic_salary or 0,allowances=emp.allowances or 0,
                    gross_salary=gross,deductions=deduction,net_salary=gross-deduction,
                    balance_payable=D(0) if paid else gross-deduction,
                    status='PAID' if paid else 'PENDING',
                    paid_at=datetime(yr,mo,28,tzinfo=timezone.utc) if paid else None,
                    paid_by='Demo Seed' if paid else '',total_period_days=D(30),payable_days=D(30),
                    salary_calculation_method='FULL'))
            summary=PayrollEntry.objects.using('default').filter(payroll_run=run).aggregate(
                gross=Sum('gross_salary'),deductions=Sum('deductions'),net=Sum('net_salary'))
            run.total_gross=summary['gross'] or D(0)
            run.total_deductions=summary['deductions'] or D(0)
            run.total_net=summary['net'] or D(0)
            run.save(using='default', update_fields=['total_gross','total_deductions','total_net'])
print('Additional employees: 10 unique DEMO-EMP-011 through DEMO-EMP-020; up to 30 payroll entries.')

products = [
 ('SSD-1TB','1TB NVMe SSD','Storage','Samsung',180,285,15),
 ('SSD-256','256GB SATA SSD','Storage','Kingston',60,100,19),
 ('RAM-16','16GB DDR4 RAM','Memory','Crucial',85,135,24),
 ('RAM-32','32GB DDR5 RAM','Memory','Corsair',180,280,8),
 ('KBD-USB','USB Keyboard','Accessories','Logitech',25,55,35),
 ('KBD-WL','Wireless Keyboard','Accessories','Logitech',40,85,18),
 ('MOUSE-WL','Wireless Mouse','Accessories','Logitech',22,50,26),
 ('USBHUB-4','4-Port USB Hub','Accessories','Generic',18,45,30),
 ('HDMI-2M','HDMI Cable 2m','Cables','Generic',8,22,45),
 ('LAN-5M','Ethernet Cable 5m','Cables','Generic',6,18,50),
 ('DISPLAY-24','24 Inch Monitor','Monitors','Dell',320,480,7),
 ('DISPLAY-27','27 Inch Monitor','Monitors','LG',520,745,5),
 ('WEBCAM','1080p USB Webcam','Accessories','Logitech',75,125,14),
 ('HEADSET','USB Headset','Accessories','JBL',45,95,21),
 ('ADAPTER','USB-C Multiport Adapter','Adapters','Generic',28,65,22),
 ('COOLING','Laptop Cooling Pad','Accessories','Generic',32,70,12),
 ('PSU-500','500W Power Supply','Components','Cooler Master',140,220,9),
 ('FAN-120','120mm Case Fan','Components','Generic',12,30,27),
 ('BATT-CMOS','CMOS Battery','Spare Parts','Generic',2,8,70),
 ('TOOL-KIT','Computer Repair Toolkit','Tools','Generic',35,85,10),
]
for code,alias in [('BR01','vat'),('BR02','non_vat')]:
    try:
        with transaction.atomic(using=alias):
            master=branch_by_code[code]
            physical=Branch.objects.using(alias).filter(pk=master.pk).first()
            if not physical or physical.branch_code != code:
                raise RuntimeError(f'{alias}: physical branch ID mismatch or missing; stop rather than creating unsafe records')
            for sku,name,category_name,brand_name,cost,price,qty in products:
                brand,_=Brand.objects.using(alias).get_or_create(name=brand_name)
                category,_=Category.objects.using(alias).get_or_create(name=category_name)
                product,_=Product.objects.using(alias).get_or_create(
                    branch_id=physical.pk,sku=f'{code}-DEMO-{sku}',
                    defaults=dict(product_name=name,brand_id=brand.pk,category_id=category.pk,
                                  condition='NEW',tax_treatment='VAT' if code=='BR01' else 'NON_VAT',reorder_level=5))
                ProductStock.objects.using(alias).get_or_create(
                    product_id=product.pk,branch_id=physical.pk,variant=None,warehouse='Main',
                    defaults=dict(current_stock=qty,reorder_level=5,average_unit_cost=D(cost),
                                  average_unit_cost_excluding_vat=D(cost),last_purchase_cost=D(cost),
                                  last_purchase_cost_excluding_vat=D(cost),
                                  last_tax_treatment='VAT' if code=='BR01' else 'NON_VAT',
                                  last_vat_percentage=D(5 if code=='BR01' else 0)))
        print(f'{code} ({alias}): up to 20 additional product/stock records created.')
    except Exception as exc:
        print(f'{code} ERROR (rolled back inventory additions): {type(exc).__name__}: {exc}')
print('Finished. Existing records remain unchanged. This script is safe to rerun.')
