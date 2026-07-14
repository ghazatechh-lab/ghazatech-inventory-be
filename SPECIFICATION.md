Build a complete backend for a **Laptop Spare Parts Inventory, Sales, HRMS, Finance, and Branch Management System** for:

# GHAZA COMPUTER
Sale & Service of Laptop Spare Parts

Use **Django + Django REST Framework** as the backend framework.

Reason for choosing Django:
- This project has many relational modules such as inventory, quotations, invoices, customers, suppliers, HRMS, attendance, payroll, branches, user roles, and reports.
- Django provides a strong ORM, migrations, authentication, permissions, admin panel, and scalable modular architecture.
- Django Admin should be used for internal back-office management.
- Django REST Framework should provide APIs for the React frontend.

Do not use FastAPI for this project unless required for a separate microservice later, such as barcode scanning, AI prediction, document OCR, or reporting workers.

---

# TECH STACK

Use:

- Python 3.12+
- Django
- Django REST Framework
- PostgreSQL
- Django Simple JWT
- django-cors-headers
- django-filter
- drf-spectacular for Swagger/OpenAPI documentation
- Celery
- Redis
- Pillow for image uploads
- django-storages + boto3 for future S3-compatible file storage
- openpyxl for Excel exports
- reportlab or WeasyPrint for PDF generation
- python-decouple or django-environ for environment variables

Use Docker and Docker Compose.

---

# BACKEND ARCHITECTURE

Create modular Django apps:

backend/
  config/
    settings/
      base.py
      development.py
      production.py
    urls.py
    celery.py
    wsgi.py
    asgi.py

  apps/
    accounts/
    branches/
    inventory/
    sales/
    purchases/
    suppliers/
    customers/
    hrms/
    finance/
    transfers/
    shipments/
    reports/
    notifications/
    audit_logs/
    common/

  requirements/
    base.txt
    development.txt
    production.txt

  docker/
  media/
  static/
  manage.py
  docker-compose.yml
  Dockerfile
  .env.example
  README.md

Use a clean service-based architecture:

Each app should contain:
- models.py
- serializers.py
- views.py
- urls.py
- permissions.py
- services.py
- filters.py
- admin.py
- tests/
- migrations/

Avoid putting complex business logic directly inside views.

---

# DATABASE

Use PostgreSQL.

Database name:
ghaza_inventory_db

Create proper:
- Foreign keys
- One-to-one relationships
- Many-to-many relationships
- Indexes
- Unique constraints
- Soft delete support where required
- Created and updated timestamps
- UUID fields for public references where useful

---

# COMMON BASE MODELS

Create reusable base models.

## TimeStampedModel

Fields:
- created_at
- updated_at

## SoftDeleteModel

Fields:
- is_deleted
- deleted_at
- deleted_by

## BranchAwareModel

Fields:
- branch
- created_by
- updated_by

Use these base models across modules where appropriate.

---

# AUTHENTICATION AND USER MANAGEMENT

Create an `accounts` app.

Use a custom user model.

## User Model Fields

- id
- username
- email
- full_name
- phone_number
- profile_image
- employee (optional one-to-one relationship)
- role
- branch
- is_active
- is_staff
- is_superuser
- last_login
- created_at
- updated_at

Authentication:
- JWT access token
- JWT refresh token
- Login using email or username
- Password reset flow
- Change password
- Logout / token blacklist
- Optional OTP login structure for future implementation

Endpoints:

POST /api/auth/login/
POST /api/auth/logout/
POST /api/auth/refresh/
POST /api/auth/change-password/
POST /api/auth/forgot-password/
POST /api/auth/reset-password/
GET /api/auth/me/

---

# ROLE BASED ACCESS CONTROL

Create role and permission management.

Roles:
- Super Admin
- Branch Manager
- Sales Manager
- Sales Executive
- Inventory Manager
- Purchase Manager
- Accountant
- HR Manager
- HR Executive
- Warehouse Staff
- Viewer

Permissions should support:
- View
- Add
- Edit
- Delete
- Approve
- Export
- Print

Implement branch-level restrictions.

Example:
- Sales Executive can create quotations and invoices only for assigned branch.
- HR Manager can manage employee records and payroll.
- Warehouse Staff can receive stock and process transfers.
- Accountant can record payments, expenses, receivables, and payables.
- Viewer has read-only access.

---

# BRANCH MODULE

Create `branches` app.

## Branch Model

Fields:
- id
- branch_code
- branch_name
- branch_type
- address
- city
- emirate
- country
- phone
- email
- manager
- is_active
- created_at
- updated_at

Example branches:
- Main Branch – Sharjah Industrial Area 2
- Dubai Branch – Deira
- Abu Dhabi Branch – Musaffah
- Ajman Branch

Endpoints:

GET /api/branches/
POST /api/branches/
GET /api/branches/{id}/
PUT /api/branches/{id}/
DELETE /api/branches/{id}/

---

# INVENTORY MODULE

Create `inventory` app.

The system should be designed specifically for laptop spare parts.

## Product Categories

- Laptop Screens
- Keyboards
- Batteries
- Chargers
- Motherboards
- RAM
- SSD / HDD
- Cooling Fans
- Hinges
- Laptop Bodies
- Touchpads
- Cables
- Accessories

## Brand Model

Fields:
- id
- name
- description
- is_active

Examples:
- Dell
- HP
- Lenovo
- Asus
- Acer
- Apple
- Microsoft Surface
- Samsung
- Toshiba

## Product Model

Fields:
- id
- product_name
- sku
- barcode
- brand
- category
- compatible_models
- supplier
- description
- product_image
- purchase_price
- retail_price
- wholesale_price
- minimum_selling_price
- warranty_period_days
- reorder_level
- rack_location
- is_active
- created_at
- updated_at

Use unique SKU and barcode fields.

## ProductStock Model

Fields:
- id
- product
- branch
- current_stock
- reserved_stock
- available_stock
- damaged_stock
- reorder_level
- last_stock_update

Available stock should be calculated as:

available_stock = current_stock - reserved_stock

## StockMovement Model

Fields:
- id
- movement_number
- product
- branch
- movement_type
- quantity
- previous_stock
- new_stock
- reference_type
- reference_id
- remarks
- performed_by
- created_at

Movement types:
- Opening Stock
- Purchase Received
- Sale
- Customer Return
- Supplier Return
- Stock Transfer Out
- Stock Transfer In
- Manual Adjustment
- Damaged Stock
- Internal Use

## Stock Adjustment Model

Fields:
- id
- adjustment_number
- product
- branch
- adjustment_type
- quantity
- reason
- remarks
- approved_by
- created_by
- status
- created_at

Adjustment reasons:
- Damaged item
- Lost item
- Physical count correction
- Return from customer
- Return to supplier
- Internal use
- Opening stock adjustment

Endpoints:

GET /api/products/
POST /api/products/
GET /api/products/{id}/
PUT /api/products/{id}/
DELETE /api/products/{id}/

GET /api/inventory/stock/
GET /api/inventory/low-stock/
GET /api/inventory/movements/
POST /api/inventory/adjustments/
POST /api/inventory/barcode/generate/
POST /api/inventory/barcode/scan/

Add filters:
- Branch
- Brand
- Category
- Stock status
- Low stock
- Search by product name, SKU, barcode, compatible model

---

# CUSTOMER MODULE

Create `customers` app.

## Customer Model

Fields:
- id
- customer_code
- customer_type
- customer_name
- contact_person
- phone
- whatsapp_number
- email
- address
- city
- emirate
- country
- trn_number
- credit_limit
- payment_terms_days
- opening_balance
- notes
- is_active
- created_at
- updated_at

Customer types:
- Walk-in
- Retail
- Wholesale
- Corporate

Important:
Create a default “Walk-in Customer” record automatically during setup.

Endpoints:

GET /api/customers/
POST /api/customers/
GET /api/customers/{id}/
PUT /api/customers/{id}/
DELETE /api/customers/{id}/
GET /api/customers/{id}/ledger/
GET /api/customers/{id}/sales-history/
GET /api/customers/{id}/outstanding/

---

# SALES MODULE

Create `sales` app.

The sales module should support quotation sales and direct walk-in sales.

## Salesperson

Use User model with Sales roles.

## Quotation Model

Fields:
- id
- quotation_number
- customer
- branch
- salesperson
- quotation_date
- valid_until
- subtotal
- discount_amount
- vat_amount
- total_amount
- status
- notes
- terms_and_conditions
- created_by
- created_at
- updated_at

Quotation statuses:
- Draft
- Sent
- Approved
- Rejected
- Expired
- Converted to Invoice

## QuotationItem Model

Fields:
- quotation
- product
- description
- quantity
- unit_price
- discount_percentage
- discount_amount
- vat_percentage
- vat_amount
- line_total

## Direct Sale / POS Sale

Direct sale must support walk-in customers.

Create `SalesInvoice` model which supports both:
- quotation based invoice
- direct walk-in invoice

Fields:
- id
- invoice_number
- quotation
- customer
- branch
- salesperson
- sale_type
- invoice_date
- due_date
- subtotal
- discount_amount
- vat_amount
- total_amount
- paid_amount
- balance_due
- payment_status
- delivery_status
- notes
- created_by
- created_at
- updated_at

Sale types:
- Quotation Sale
- Direct Sale
- Walk-in Sale

Payment statuses:
- Paid
- Partially Paid
- Unpaid
- Overdue
- Cancelled

Delivery statuses:
- Pending
- Packed
- Out for Delivery
- Delivered
- Returned
- Cancelled

## SalesInvoiceItem Model

Fields:
- invoice
- product
- description
- quantity
- unit_price
- discount_percentage
- discount_amount
- vat_percentage
- vat_amount
- line_total

When invoice is confirmed:
- Deduct stock from selected branch.
- Create StockMovement records.
- Prevent negative stock unless user has special permission.
- Update customer outstanding amount.
- Create audit log.

## Sales Credit Note Model

Fields:
- id
- credit_note_number
- invoice
- customer
- branch
- reason
- subtotal
- vat_amount
- total_amount
- status
- notes
- created_by
- created_at

Reasons:
- Damaged product
- Wrong item delivered
- Return accepted
- Pricing correction
- Invoice correction

When credit note is approved:
- Restore stock if physical return is enabled.
- Reduce invoice balance.
- Update customer ledger.
- Create audit log.

## Sales Payment Model

Fields:
- id
- receipt_number
- customer
- invoice
- branch
- payment_date
- payment_method
- amount
- reference_number
- remarks
- received_by
- created_at

Payment methods:
- Cash
- Card
- Bank Transfer
- Credit
- Cheque
- Split Payment

Endpoints:

GET /api/sales/quotations/
POST /api/sales/quotations/
GET /api/sales/quotations/{id}/
PUT /api/sales/quotations/{id}/
POST /api/sales/quotations/{id}/send/
POST /api/sales/quotations/{id}/convert-to-invoice/

GET /api/sales/invoices/
POST /api/sales/invoices/
GET /api/sales/invoices/{id}/
PUT /api/sales/invoices/{id}/
POST /api/sales/invoices/{id}/confirm/
POST /api/sales/invoices/{id}/cancel/
POST /api/sales/invoices/{id}/add-payment/

POST /api/sales/direct-sale/
POST /api/sales/pos/hold/
POST /api/sales/pos/complete/

GET /api/sales/credit-notes/
POST /api/sales/credit-notes/
POST /api/sales/credit-notes/{id}/approve/

GET /api/sales/payments/
POST /api/sales/payments/

---

# SUPPLIER MODULE

Create `suppliers` app.

## Supplier Model

Fields:
- id
- supplier_code
- supplier_name
- supplier_type
- contact_person
- phone
- email
- address
- city
- country
- trn_number
- credit_limit
- payment_terms_days
- opening_balance
- notes
- is_active
- created_at
- updated_at

Supplier types:
- Local Supplier
- UAE Distributor
- China Supplier
- Dubai Market Supplier
- Manufacturer
- Import Supplier

Endpoints:

GET /api/suppliers/
POST /api/suppliers/
GET /api/suppliers/{id}/
PUT /api/suppliers/{id}/
DELETE /api/suppliers/{id}/
GET /api/suppliers/{id}/ledger/
GET /api/suppliers/{id}/purchase-history/

---

# PURCHASE MODULE

Create `purchases` app.

## PurchaseOrder Model

Fields:
- id
- po_number
- supplier
- branch
- order_date
- expected_delivery_date
- subtotal
- discount_amount
- vat_amount
- total_amount
- status
- payment_status
- notes
- created_by
- approved_by
- created_at
- updated_at

Statuses:
- Draft
- Sent
- Partially Received
- Received
- Cancelled

## PurchaseOrderItem Model

Fields:
- purchase_order
- product
- description
- quantity
- received_quantity
- unit_price
- discount_amount
- vat_amount
- line_total

## GoodsReceivedNote Model

Fields:
- id
- grn_number
- purchase_order
- supplier
- branch
- received_date
- received_by
- notes
- status
- created_at

## GoodsReceivedItem Model

Fields:
- grn
- product
- ordered_quantity
- received_quantity
- damaged_quantity
- accepted_quantity
- rack_location
- remarks

When GRN is confirmed:
- Increase branch stock.
- Create StockMovement records.
- Update purchase order received quantities.
- Update purchase order status.

## SupplierBill Model

Fields:
- id
- bill_number
- supplier
- purchase_order
- branch
- bill_date
- due_date
- total_amount
- paid_amount
- balance_due
- payment_status
- notes
- created_at

## SupplierPayment Model

Fields:
- id
- payment_number
- supplier
- supplier_bill
- branch
- payment_date
- payment_method
- amount
- reference_number
- notes
- paid_by
- created_at

## SupplierReturn Model

Fields:
- id
- return_number
- supplier
- grn
- branch
- return_date
- reason
- total_amount
- status
- notes
- created_at

When supplier return is confirmed:
- Deduct stock.
- Create StockMovement.
- Update supplier payable balance.

---

# HRMS MODULE

Create `hrms` app.

This module must support UAE employee documents and expiry tracking.

## Department Model

Fields:
- id
- name
- description
- manager
- is_active

Departments:
- Sales
- Inventory
- Warehouse
- Purchase
- Finance
- HR
- Management
- Delivery
- IT Support

## Designation Model

Fields:
- id
- title
- department
- description
- is_active

Examples:
- Sales Executive
- Branch Manager
- Inventory Manager
- Warehouse Assistant
- HR Executive
- Accountant
- Delivery Driver
- Technician

## Employee Model

Fields:

### Personal Details
- id
- employee_code
- first_name
- last_name
- full_name
- profile_image
- gender
- date_of_birth
- nationality
- personal_mobile
- personal_email
- address
- emergency_contact_name
- emergency_contact_number
- emergency_contact_relationship

### Employment Details
- branch
- department
- designation
- reporting_manager
- joining_date
- employment_type
- work_email
- employment_status

### Salary Details
- basic_salary
- housing_allowance
- transport_allowance
- other_allowance
- bank_name
- bank_account_number
- iban_number
- wps_number

### UAE Legal Documents
- passport_number
- passport_issue_date
- passport_expiry_date
- passport_copy
- visa_number
- visa_issue_date
- visa_expiry_date
- visa_copy
- emirates_id_number
- emirates_id_issue_date
- emirates_id_expiry_date
- emirates_id_copy
- labour_card_number
- labour_card_expiry_date
- driving_license_number
- driving_license_expiry_date
- insurance_policy_number
- insurance_expiry_date

### System Fields
- status
- notes
- created_at
- updated_at

Employment statuses:
- Active
- On Leave
- Resigned
- Terminated
- Probation

Employment types:
- Full Time
- Part Time
- Contract
- Internship

## EmployeeDocument Model

Fields:
- employee
- document_type
- document_number
- issue_date
- expiry_date
- attachment
- notes
- reminder_days_before
- status

Document types:
- Passport
- Visa
- Emirates ID
- Labour Card
- Driving License
- Medical Insurance
- Employment Contract
- Offer Letter
- Educational Certificate
- Experience Certificate
- Other

## Attendance Model

Fields:
- employee
- branch
- attendance_date
- check_in_time
- check_out_time
- working_hours
- overtime_hours
- attendance_status
- remarks
- marked_by

Attendance statuses:
- Present
- Absent
- Late
- Half Day
- Work From Home
- On Leave
- Holiday

## LeaveType Model

Fields:
- name
- annual_limit
- is_paid
- is_active

Leave types:
- Annual Leave
- Sick Leave
- Emergency Leave
- Unpaid Leave
- Maternity Leave
- Paternity Leave
- Leave Without Pay

## LeaveRequest Model

Fields:
- employee
- leave_type
- start_date
- end_date
- total_days
- reason
- attachment
- status
- approved_by
- approval_remarks
- created_at
- updated_at

Statuses:
- Pending
- Approved
- Rejected
- Cancelled

## Payroll Model

Fields:
- payroll_number
- employee
- branch
- payroll_month
- basic_salary
- housing_allowance
- transport_allowance
- other_allowance
- overtime_amount
- bonus_amount
- leave_deduction
- loan_deduction
- advance_salary_deduction
- other_deduction
- gross_salary
- total_deduction
- net_salary
- payment_status
- paid_date
- payment_reference
- generated_by
- created_at

Payroll statuses:
- Draft
- Generated
- Approved
- Paid
- Cancelled

Endpoints:

GET /api/hrms/employees/
POST /api/hrms/employees/
GET /api/hrms/employees/{id}/
PUT /api/hrms/employees/{id}/
DELETE /api/hrms/employees/{id}/

GET /api/hrms/employees/{id}/documents/
POST /api/hrms/employees/{id}/documents/

GET /api/hrms/attendance/
POST /api/hrms/attendance/
POST /api/hrms/attendance/check-in/
POST /api/hrms/attendance/check-out/

GET /api/hrms/leaves/
POST /api/hrms/leaves/
POST /api/hrms/leaves/{id}/approve/
POST /api/hrms/leaves/{id}/reject/

GET /api/hrms/payroll/
POST /api/hrms/payroll/generate/
POST /api/hrms/payroll/{id}/approve/
POST /api/hrms/payroll/{id}/mark-paid/
GET /api/hrms/payroll/{id}/payslip/

GET /api/hrms/document-expiry/
GET /api/hrms/document-expiry/upcoming/
GET /api/hrms/dashboard/

---

# DOCUMENT EXPIRY AUTOMATION

Use Celery and Redis.

Create scheduled Celery tasks to run daily.

Tasks:
- Check visa expiry
- Check passport expiry
- Check Emirates ID expiry
- Check labour card expiry
- Check driving license expiry
- Check medical insurance expiry

Create alerts for:
- Already expired
- Expiring within 7 days
- Expiring within 30 days
- Expiring within 60 days

Notification recipients:
- HR Manager
- Branch Manager
- Super Admin

---

# FINANCE MODULE

Create `finance` app.

## ExpenseCategory Model

Categories:
- Shop Rent
- Electricity
- Internet
- Employee Salary
- Transportation
- Delivery Charges
- Office Supplies
- Repair Charges
- Marketing
- Other Expenses

## Expense Model

Fields:
- expense_number
- branch
- category
- expense_date
- amount
- payment_method
- supplier
- attachment
- notes
- approved_by
- created_by
- created_at

Payment methods:
- Cash
- Card
- Bank Transfer
- Cheque

## CashRegister Model

Fields:
- branch
- opening_balance
- total_cash_sales
- total_cash_expenses
- closing_balance
- register_date
- closed_by
- status

## BankAccount Model

Fields:
- branch
- bank_name
- account_name
- account_number
- iban_number
- opening_balance
- current_balance
- is_active

## LedgerEntry Model

Create a reusable customer and supplier ledger.

Fields:
- entry_number
- branch
- ledger_type
- customer
- supplier
- transaction_type
- reference_type
- reference_id
- debit_amount
- credit_amount
- balance
- transaction_date
- remarks
- created_at

Ledger types:
- Customer
- Supplier

Transaction types:
- Invoice
- Payment
- Credit Note
- Purchase Bill
- Supplier Payment
- Supplier Return
- Opening Balance

Endpoints:

GET /api/finance/expenses/
POST /api/finance/expenses/
GET /api/finance/customer-receivables/
GET /api/finance/supplier-payables/
GET /api/finance/cash-register/
GET /api/finance/bank-accounts/
GET /api/finance/ledger/

---

# STOCK TRANSFER MODULE

Create `transfers` app.

## StockTransfer Model

Fields:
- id
- transfer_number
- from_branch
- to_branch
- requested_by
- approved_by
- dispatched_by
- received_by
- transfer_date
- dispatch_date
- received_date
- status
- notes
- created_at

Statuses:
- Draft
- Requested
- Approved
- Dispatched
- In Transit
- Received
- Cancelled

## StockTransferItem Model

Fields:
- transfer
- product
- requested_quantity
- dispatched_quantity
- received_quantity
- damaged_quantity
- remarks

Business workflow:
1. Branch creates transfer request.
2. Manager approves request.
3. Source branch dispatches stock.
4. Stock deducted from source branch.
5. Destination branch receives stock.
6. Stock added to destination branch.
7. Create stock movement records for both branches.

Endpoints:

GET /api/transfers/
POST /api/transfers/
GET /api/transfers/{id}/
POST /api/transfers/{id}/approve/
POST /api/transfers/{id}/dispatch/
POST /api/transfers/{id}/receive/
POST /api/transfers/{id}/cancel/

---

# SHIPMENT MODULE

Create `shipments` app.

## Shipment Model

Fields:
- shipment_number
- invoice
- customer
- branch
- delivery_address
- delivery_person
- delivery_date
- tracking_number
- status
- notes
- created_at
- updated_at

Statuses:
- Pending
- Packed
- Out for Delivery
- Delivered
- Returned
- Cancelled

## ShipmentTrackingLog Model

Fields:
- shipment
- status
- location
- remarks
- updated_by
- created_at

Endpoints:

GET /api/shipments/
POST /api/shipments/
GET /api/shipments/{id}/
PUT /api/shipments/{id}/
POST /api/shipments/{id}/update-status/
GET /api/shipments/{id}/tracking/

---

# NOTIFICATIONS MODULE

Create `notifications` app.

## Notification Model

Fields:
- user
- branch
- notification_type
- title
- message
- priority
- is_read
- related_model
- related_object_id
- created_at

Types:
- Low Stock Alert
- Invoice Overdue
- Payment Due
- Visa Expiry
- Passport Expiry
- Emirates ID Expiry
- Leave Approval
- Purchase Order Pending
- Stock Transfer Received
- Customer Payment Received

Priorities:
- Urgent
- Warning
- Information
- Success

Endpoints:

GET /api/notifications/
POST /api/notifications/{id}/mark-read/
POST /api/notifications/mark-all-read/

---

# AUDIT LOG MODULE

Create `audit_logs` app.

## AuditLog Model

Fields:
- user
- branch
- module
- action
- description
- object_type
- object_id
- ip_address
- created_at

Actions:
- Create
- Update
- Delete
- Approve
- Reject
- Login
- Logout
- Payment Received
- Stock Adjusted
- Invoice Confirmed

Use middleware or service layer to automatically capture important actions.

Endpoint:

GET /api/audit-logs/

Allow filters:
- User
- Branch
- Module
- Action
- Date range

---

# REPORTS MODULE

Create `reports` app.

Provide API endpoints for:

- Dashboard summary
- Sales report
- Sales by customer
- Sales by product
- Sales by category
- Salesperson performance
- Purchase report
- Purchase by supplier
- Inventory valuation report
- Low stock report
- Stock movement report
- Branch stock report
- Profit margin report
- Expense report
- Customer outstanding report
- Supplier payable report
- Employee attendance report
- Leave report
- Payroll report
- Visa/passport/Emirates ID expiry report

Reports should support:
- Date range filter
- Branch filter
- Customer filter
- Supplier filter
- Product filter
- Employee filter
- Pagination
- Excel export
- PDF export

Example endpoint structure:

GET /api/reports/dashboard/
GET /api/reports/sales/
GET /api/reports/inventory-valuation/
GET /api/reports/low-stock/
GET /api/reports/customer-outstanding/
GET /api/reports/employee-document-expiry/
GET /api/reports/export/excel/
GET /api/reports/export/pdf/

---

# DASHBOARD API

Create a dashboard summary endpoint.

GET /api/dashboard/

Return:

- Total stock value
- Total sales this month
- Total purchases this month
- Total receivables
- Total payables
- Total expenses
- Low stock item count
- Pending quotation count
- Recent invoices
- Recent transfers
- Low stock products
- Pending customer payments
- Recent activities
- Sales versus purchase chart data
- Monthly sales trend
- Stock value by branch
- Top selling products
- Sales by category

All figures should support branch filtering.

Example:

GET /api/dashboard/?branch_id=1

---

# API QUALITY REQUIREMENTS

Use:

- ViewSets where appropriate
- Routers for CRUD APIs
- Generic views for simple APIs
- Service classes for business workflows
- Serializer validation
- Atomic database transactions for invoices, GRNs, transfers, payments, and payroll
- Proper error responses
- Pagination
- Filtering
- Search
- Ordering
- Permissions
- Logging
- Swagger documentation

Use response format:

{
  "success": true,
  "message": "Invoice created successfully",
  "data": {}
}

Use validation error format:

{
  "success": false,
  "message": "Validation failed",
  "errors": {
    "field_name": ["This field is required"]
  }
}

---

# IMPORTANT BUSINESS RULES

1. Products cannot have duplicate SKU or barcode.
2. Stock should be maintained separately for each branch.
3. Confirming a sales invoice should deduct stock.
4. Confirming a GRN should increase stock.
5. Confirming a transfer dispatch should deduct stock from source branch.
6. Confirming a transfer receipt should add stock to destination branch.
7. Credit notes can restore stock when returned products are accepted.
8. Sales invoices should update customer receivables.
9. Customer payments should reduce outstanding balance.
10. Supplier bills should update supplier payables.
11. Supplier payments should reduce payables.
12. Payroll should calculate gross salary, deductions, and net salary.
13. HR document expiry should automatically create notifications.
14. All important create/update/delete actions should create audit logs.
15. Branch users should only access data from their assigned branch unless they are Super Admin.
16. Do not allow negative inventory without special permission.
17. Use VAT calculation support, default VAT set to 5%.
18. Use AED currency formatting in APIs where required.

---

# DJANGO ADMIN

Configure Django Admin for all major models.

Admin should support:
- Search
- Filters
- Inline items for invoices, quotations, purchase orders, transfers, employee documents
- Read-only audit timestamps
- Bulk actions
- Export actions where possible

Create a clean, useful internal admin setup.

---

# SEED DATA

Create a management command:

python manage.py seed_data

Seed:

## Branches
- Main Branch – Sharjah Industrial Area 2
- Dubai Branch – Deira
- Abu Dhabi Branch – Musaffah
- Ajman Branch

## Users
- Super Admin
- Sales Executive
- Inventory Manager
- HR Manager
- Accountant
- Warehouse Staff

## Employees
- Ahmed Rashid
- Mohammed Aslam
- Fathima Noor
- Sameer Ali
- Riyas Kareem
- Ayesha Rahman
- Nabeel Hassan

## Customers
- Al Noor Computer Trading LLC
- Tech Zone Electronics
- Fast Laptop Repair Center
- Al Ain IT Solutions
- Walk-in Customer
- Future Star Computers

## Suppliers
- Shenzhen Laptop Parts Co.
- Dubai Computer Parts Trading
- Laptop World Wholesale LLC
- TechSource Electronics
- Guangzhou Spare Parts Supplier

## Products
Create at least 25 laptop spare parts including:
- Dell Latitude 5400 Keyboard
- HP EliteBook 840 G5 Screen
- Lenovo ThinkPad T480 Battery
- Asus X515 Charger
- MacBook Air M1 Screen
- Dell Inspiron 15 Fan
- Acer Aspire A315 Hinges
- Samsung Laptop SSD 512GB
- DDR4 RAM 16GB
- Universal Laptop Touchpad
- Laptop Charging Port
- Dell Latitude 7490 Battery
- HP Pavilion Keyboard
- Lenovo Charger 65W
- Acer Laptop Screen 15.6 inch
- Asus Laptop DC Jack
- MacBook Pro Trackpad
- Dell Laptop Bottom Cover
- HP Laptop Cooling Fan
- M.2 NVMe SSD 1TB
- DDR4 RAM 8GB
- Laptop Screen Cable
- Universal Webcam
- Laptop Speaker Set
- Laptop WiFi Card

---

# DOCKER SETUP

Create:

- Dockerfile
- docker-compose.yml
- PostgreSQL service
- Redis service
- Django backend service
- Celery worker service
- Celery beat service

Use environment variables through `.env`.

Example `.env.example`:

DEBUG=True
SECRET_KEY=change-me
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=ghaza_inventory_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432

REDIS_URL=redis://redis:6379/0

JWT_ACCESS_TOKEN_LIFETIME=60
JWT_REFRESH_TOKEN_LIFETIME=7

DEFAULT_VAT_PERCENTAGE=5

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=

---

# DOCUMENTATION

Create a complete README.md containing:

1. Project overview
2. Technology stack
3. Installation steps
4. Docker setup instructions
5. Local setup instructions
6. Environment variable configuration
7. Database migration commands
8. Seed data command
9. Create superuser command
10. Run Celery worker command
11. Run Celery beat command
12. Swagger API URL
13. API authentication usage
14. Project folder structure
15. Main business workflows

Commands should include:

docker compose up --build

docker compose exec backend python manage.py migrate

docker compose exec backend python manage.py seed_data

docker compose exec backend python manage.py createsuperuser

Swagger URL:

/api/docs/

OpenAPI schema:

/api/schema/

---

# FINAL EXPECTATION

Generate a production-ready Django REST Framework backend foundation with:

- Modular apps
- PostgreSQL database models
- JWT authentication
- Roles and branch-based permissions
- Inventory management
- Sales quotations
- Walk-in direct sales / POS
- Sales invoices
- Customer payments
- Credit notes
- Purchase orders
- GRN stock receiving
- Supplier bills and payments
- Stock transfers between branches
- Shipment tracking
- HRMS with employee details
- Visa, passport, Emirates ID, labour card, insurance expiry tracking
- Attendance
- Leave management
- Payroll
- Expenses and ledgers
- Notifications
- Audit logs
- Reports
- Swagger documentation
- Celery scheduled expiry alerts
- Docker setup
- Dummy seed data
- Django admin configuration
- Clean code with services, serializers, validations, permissions, and tests

Build the backend in a way that the existing React frontend can connect to it easily through REST APIs.