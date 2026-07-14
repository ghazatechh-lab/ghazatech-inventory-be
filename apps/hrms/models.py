from django.db import models
from apps.common.models import TimeStampedModel


class Department(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    manager = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)


class Designation(TimeStampedModel):
    title = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)


class Employee(TimeStampedModel):
    employee_code = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    profile_image = models.ImageField(upload_to="employees/", null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=80, blank=True)
    personal_mobile = models.CharField(max_length=30, blank=True)
    personal_email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_number = models.CharField(max_length=30, blank=True)
    emergency_contact_relationship = models.CharField(max_length=80, blank=True)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    designation = models.ForeignKey(Designation, on_delete=models.PROTECT)
    reporting_manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL
    )
    joining_date = models.DateField()
    employment_type = models.CharField(max_length=30, default="FULL_TIME")
    work_email = models.EmailField(blank=True)
    employment_status = models.CharField(max_length=30, default="ACTIVE")
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=100, blank=True)
    iban_number = models.CharField(max_length=100, blank=True)
    wps_number = models.CharField(max_length=100, blank=True)
    passport_number = models.CharField(max_length=100, blank=True)
    passport_issue_date = models.DateField(null=True, blank=True)
    passport_expiry_date = models.DateField(null=True, blank=True)
    passport_copy = models.FileField(upload_to="employee_docs/", null=True, blank=True)
    visa_number = models.CharField(max_length=100, blank=True)
    visa_issue_date = models.DateField(null=True, blank=True)
    visa_expiry_date = models.DateField(null=True, blank=True)
    visa_copy = models.FileField(upload_to="employee_docs/", null=True, blank=True)
    emirates_id_number = models.CharField(max_length=100, blank=True)
    emirates_id_issue_date = models.DateField(null=True, blank=True)
    emirates_id_expiry_date = models.DateField(null=True, blank=True)
    emirates_id_copy = models.FileField(
        upload_to="employee_docs/", null=True, blank=True
    )
    labour_card_number = models.CharField(max_length=100, blank=True)
    labour_card_expiry_date = models.DateField(null=True, blank=True)
    driving_license_number = models.CharField(max_length=100, blank=True)
    driving_license_expiry_date = models.DateField(null=True, blank=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    insurance_expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, default="ACTIVE")
    notes = models.TextField(blank=True)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class EmployeeDocument(TimeStampedModel):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=50)
    document_number = models.CharField(max_length=100, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    attachment = models.FileField(
        upload_to="employee_documents/", null=True, blank=True
    )
    notes = models.TextField(blank=True)
    reminder_days_before = models.PositiveIntegerField(default=30)
    status = models.CharField(max_length=30, default="ACTIVE")


class Attendance(TimeStampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    attendance_date = models.DateField()
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    working_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    attendance_status = models.CharField(max_length=30, default="PRESENT")
    remarks = models.TextField(blank=True)
    marked_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = ("employee", "attendance_date")


class LeaveType(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    annual_limit = models.PositiveIntegerField(default=0)
    is_paid = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)


class LeaveRequest(TimeStampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.TextField()
    attachment = models.FileField(upload_to="leave_attachments/", null=True, blank=True)
    status = models.CharField(max_length=20, default="PENDING")
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    approval_remarks = models.TextField(blank=True)


class Payroll(TimeStampedModel):
    payroll_number = models.CharField(max_length=50, unique=True)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)
    payroll_month = models.DateField()
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overtime_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bonus_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    leave_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loan_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance_salary_deduction = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    other_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, default="DRAFT")
    paid_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    generated_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
