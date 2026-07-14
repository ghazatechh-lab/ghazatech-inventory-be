from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.branches.models import Branch
from apps.accounts.models import Role
from apps.inventory.models import Brand,Category,Product,ProductStock
from apps.customers.models import Customer
from apps.suppliers.models import Supplier
from apps.hrms.models import Department,Designation,Employee
from datetime import date
class Command(BaseCommand):
 help='Seeds Ghaza Computer starter data'
 def handle(self,*args,**opts):
  roles=['Super Admin','Sales Executive','Inventory Manager','HR Manager','Accountant','Warehouse Staff']
  for name in roles: Role.objects.get_or_create(name=name,defaults={'code':name.upper().replace(' ','_')})
  branch_data=[('MAIN','Main Branch – Sharjah Industrial Area 2','Sharjah'),('DUB','Dubai Branch – Deira','Dubai'),('AUH','Abu Dhabi Branch – Musaffah','Abu Dhabi'),('AJM','Ajman Branch','Ajman')]
  branches=[]
  for code,name,city in branch_data: branches.append(Branch.objects.get_or_create(branch_code=code,defaults={'branch_name':name,'city':city,'emirate':city})[0])
  User=get_user_model(); admin,_=User.objects.get_or_create(email='admin@ghazacomputer.local',defaults={'username':'admin','full_name':'Super Admin','role':Role.objects.get(name='Super Admin'),'branch':branches[0],'is_staff':True,'is_superuser':True});admin.set_password('Admin@123');admin.save()
  for i,name in enumerate(roles[1:],1):
   u,_=User.objects.get_or_create(email=f'{name.lower().replace(" ",".")}@ghazacomputer.local',defaults={'username':name.lower().replace(' ','.'),'full_name':name,'role':Role.objects.get(name=name),'branch':branches[i%len(branches)]});u.set_password('Password@123');u.save()
  for n in ['Dell','HP','Lenovo','Asus','Acer','Apple','Microsoft Surface','Samsung','Toshiba']: Brand.objects.get_or_create(name=n)
  for n in ['Laptop Screens','Keyboards','Batteries','Chargers','Motherboards','RAM','SSD / HDD','Cooling Fans','Hinges','Laptop Bodies','Touchpads','Cables','Accessories']:Category.objects.get_or_create(name=n)
  for code,name,typ in [('WALKIN','Walk-in Customer','Walk-in'),('C001','Al Noor Computer Trading LLC','Wholesale'),('C002','Tech Zone Electronics','Retail'),('C003','Fast Laptop Repair Center','Corporate'),('C004','Al Ain IT Solutions','Corporate'),('C005','Future Star Computers','Wholesale')]:Customer.objects.get_or_create(customer_code=code,defaults={'customer_name':name,'customer_type':typ})
  for i,name in enumerate(['Shenzhen Laptop Parts Co.','Dubai Computer Parts Trading','Laptop World Wholesale LLC','TechSource Electronics','Guangzhou Spare Parts Supplier'],1):Supplier.objects.get_or_create(supplier_code=f'S{i:03}',defaults={'supplier_name':name})
  d=Department.objects.get_or_create(name='Sales')[0];des=Designation.objects.get_or_create(title='Sales Executive',department=d)[0]
  for i,n in enumerate(['Ahmed Rashid','Mohammed Aslam','Fathima Noor','Sameer Ali','Riyas Kareem','Ayesha Rahman','Nabeel Hassan'],1):
   f,*rest=n.split();Employee.objects.get_or_create(employee_code=f'E{i:03}',defaults={'first_name':f,'last_name':' '.join(rest),'branch':branches[i%4],'department':d,'designation':des,'joining_date':date.today()})
  names=['Dell Latitude 5400 Keyboard','HP EliteBook 840 G5 Screen','Lenovo ThinkPad T480 Battery','Asus X515 Charger','MacBook Air M1 Screen','Dell Inspiron 15 Fan','Acer Aspire A315 Hinges','Samsung Laptop SSD 512GB','DDR4 RAM 16GB','Universal Laptop Touchpad','Laptop Charging Port','Dell Latitude 7490 Battery','HP Pavilion Keyboard','Lenovo Charger 65W','Acer Laptop Screen 15.6 inch','Asus Laptop DC Jack','MacBook Pro Trackpad','Dell Laptop Bottom Cover','HP Laptop Cooling Fan','M.2 NVMe SSD 1TB','DDR4 RAM 8GB','Laptop Screen Cable','Universal Webcam','Laptop Speaker Set','Laptop WiFi Card']
  brand=Brand.objects.first();cat=Category.objects.first();supplier=Supplier.objects.first()
  for i,n in enumerate(names,1):
   p,_=Product.objects.get_or_create(sku=f'GHZ-{i:04}',defaults={'product_name':n,'barcode':f'629000000{i:04}','brand':brand,'category':cat,'supplier':supplier,'purchase_price':50+i*5,'retail_price':80+i*8,'reorder_level':5});ProductStock.objects.get_or_create(product=p,branch=branches[0],defaults={'current_stock':20,'reorder_level':5})
  self.stdout.write(self.style.SUCCESS('Seed completed. Admin: admin@ghazacomputer.local / Admin@123'))
