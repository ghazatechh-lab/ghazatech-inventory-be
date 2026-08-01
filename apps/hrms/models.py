from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from apps.common.models import TimeStampedModel


def employee_document_path(instance, filename):
    return f"hrms/employees/{instance.employee_id}/documents/{filename}"


class Department(TimeStampedModel):
    name = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
    )
    code = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(
        null=True,
        blank=True,
        default=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name or self.code or f"Department #{self.pk}"


class Designation(TimeStampedModel):
    # New field: nullable during the transition for existing rows.
    name = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    # Legacy field retained to avoid an unsafe automatic rename.
    designation_name = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="designations",
    )
    is_active = models.BooleanField(
        null=True,
        blank=True,
        default=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name or self.designation_name or f"Designation #{self.pk}"


class Employee(TimeStampedModel):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("ON_LEAVE", "On Leave"),
        ("PROBATION", "Probation"),
        ("RESIGNED", "Resigned"),
        ("TERMINATED", "Terminated"),
        ("INACTIVE", "Inactive"),
    ]
    TYPE_CHOICES = [
        ("FULL_TIME", "Full Time"),
        ("PART_TIME", "Part Time"),
        ("CONTRACT", "Contract"),
        ("INTERN", "Intern"),
    ]

    employee_code = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
    )
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="employees",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
    )
    designation = models.ForeignKey(
        Designation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)
    nationality = models.CharField(max_length=80, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    profile_image = models.ImageField(
        upload_to="hrms/employees/profile/", null=True, blank=True
    )

    employment_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES,
        null=True,
        blank=True,
        default="FULL_TIME",
    )
    employment_status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="ACTIVE",
    )

    passport_number = models.CharField(max_length=80, null=True, blank=True)
    passport_issue_date = models.DateField(null=True, blank=True)
    passport_expiry_date = models.DateField(null=True, blank=True)

    emirates_id_number = models.CharField(max_length=80, null=True, blank=True)
    emirates_id_issue_date = models.DateField(null=True, blank=True)
    emirates_id_expiry_date = models.DateField(null=True, blank=True)

    visa_number = models.CharField(max_length=80, null=True, blank=True)
    visa_type = models.CharField(max_length=80, null=True, blank=True)
    visa_sponsor = models.CharField(max_length=150, null=True, blank=True)
    visa_issue_date = models.DateField(null=True, blank=True)
    visa_expiry_date = models.DateField(null=True, blank=True)
    visa_status = models.CharField(
        max_length=30, null=True, blank=True, default="VALID"
    )

    labor_contract_number = models.CharField(max_length=100, null=True, blank=True)
    labor_contract_type = models.CharField(max_length=80, null=True, blank=True)
    labor_contract_start_date = models.DateField(null=True, blank=True)
    labor_contract_end_date = models.DateField(null=True, blank=True)
    labor_contract_status = models.CharField(
        max_length=30, null=True, blank=True, default="ACTIVE"
    )

    # Legacy employee-document fields retained as separate fields.
    # These are NOT aliases for labor-contract dates.
    driving_license_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )
    driving_license_issue_date = models.DateField(
        null=True,
        blank=True,
    )
    driving_license_expiry_date = models.DateField(
        null=True,
        blank=True,
    )

    insurance_policy_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )
    insurance_provider = models.CharField(
        max_length=150,
        null=True,
        blank=True,
    )
    insurance_issue_date = models.DateField(
        null=True,
        blank=True,
    )
    insurance_expiry_date = models.DateField(
        null=True,
        blank=True,
    )

    basic_salary = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, default=0
    )
    allowances = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, default=0
    )
    address = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(
        null=True,
        blank=True,
        default=True,
    )

    class Meta:
        ordering = ["first_name", "last_name", "id"]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name or ''}".strip()

    @property
    def total_salary(self):
        return (self.basic_salary or 0) + (self.allowances or 0)

    def __str__(self):
        return f"{self.employee_code} - {self.full_name}"


class EmployeeDocument(TimeStampedModel):
    TYPE_CHOICES = [
        ("PASSPORT", "Passport"),
        ("EMIRATES_ID", "Emirates ID"),
        ("VISA", "Visa"),
        ("LABOR_CONTRACT", "Labor Contract"),
        ("EDUCATION", "Education Certificate"),
        ("MEDICAL", "Medical"),
        ("INSURANCE", "Insurance"),
        ("OTHER", "Other"),
    ]
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    document_type = models.CharField(
        max_length=40,
        choices=TYPE_CHOICES,
        null=True,
        blank=True,
    )
    title = models.CharField(
        max_length=150,
        null=True,
        blank=True,
    )
    document_number = models.CharField(max_length=100, null=True, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    file = models.FileField(
        upload_to=employee_document_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "jpg",
                    "jpeg",
                    "png",
                    "doc",
                    "docx",
                ]
            )
        ],
        null=True,
        blank=True,
    )
    notes = models.TextField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_employee_documents",
    )

    class Meta:
        ordering = ["expiry_date", "-created_at"]


class Attendance(TimeStampedModel):
    STATUS_CHOICES = [
        ("PRESENT", "Present"),
        ("ABSENT", "Absent"),
        ("LATE", "Late"),
        ("LEAVE", "Leave"),
        ("HALF_DAY", "Half Day"),
        ("HOLIDAY", "Holiday"),
        ("WEEK_OFF", "Week Off"),
    ]
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    date = models.DateField(
        null=True,
        blank=True,
    )
    # New normalized names.
    check_in = models.TimeField(
        null=True,
        blank=True,
    )
    check_out = models.TimeField(
        null=True,
        blank=True,
    )

    # Legacy names retained temporarily so Django does not force or guess a rename.
    check_in_time = models.TimeField(
        null=True,
        blank=True,
    )
    check_out_time = models.TimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="PRESENT",
    )
    working_hours = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True, default=0
    )
    overtime_hours = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True, default=0
    )
    remarks = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["-date", "employee__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date"], name="unique_employee_attendance_date"
            )
        ]


class LeaveType(TimeStampedModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    code = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
    )
    annual_limit = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    is_paid = models.BooleanField(
        null=True,
        blank=True,
        default=True,
    )
    requires_document = models.BooleanField(
        null=True,
        blank=True,
        default=False,
    )
    is_active = models.BooleanField(
        null=True,
        blank=True,
        default=True,
    )

    def __str__(self):
        return self.name


class LeaveBalance(TimeStampedModel):
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="leave_balances",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="balances",
    )
    year = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    entitled_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    used_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "leave_type", "year"],
                name="unique_employee_leave_balance",
            )
        ]

    @property
    def remaining_days(self):
        return (self.entitled_days or 0) - (self.used_days or 0)


class LeaveRequest(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    ]
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="leave_requests",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="leave_requests",
    )
    from_date = models.DateField(
        null=True,
        blank=True,
    )
    to_date = models.DateField(
        null=True,
        blank=True,
    )
    days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        default=1,
    )
    reason = models.TextField(
        null=True,
        blank=True,
    )
    supporting_document = models.FileField(
        upload_to="hrms/leaves/", null=True, blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="PENDING",
    )
    action_remarks = models.TextField(null=True, blank=True)
    actioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actioned_leave_requests",
    )
    actioned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class SalaryRevision(TimeStampedModel):
    PAYROLL_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]

    REASON_CHOICES = [
        ("JOINING", "Joining"),
        ("ANNUAL_INCREMENT", "Annual Increment"),
        ("PROMOTION", "Promotion"),
        ("CORRECTION", "Salary Correction"),
        ("OTHER", "Other"),
    ]
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="salary_revisions",
    )
    reason = models.CharField(
        max_length=40,
        choices=REASON_CHOICES,
        null=True,
        blank=True,
    )
    effective_from = models.DateField(
        null=True,
        blank=True,
    )
    effective_to = models.DateField(
        null=True,
        blank=True,
    )
    basic_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    allowances = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    deductions = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, default=0
    )
    payroll_status = models.CharField(
        max_length=20,
        choices=PAYROLL_STATUS_CHOICES,
        null=True,
        blank=True,
        default="PAID",
    )
    payment_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=120, null=True, blank=True)
    approved_by_name = models.CharField(max_length=150, null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_salary_revisions",
    )
    notes = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-effective_from", "-id"]

    @property
    def total_salary(self):
        return (self.basic_salary or 0) + (self.allowances or 0)


class PayrollRun(TimeStampedModel):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("PROCESSING", "Processing"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]
    period = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payroll_runs",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="DRAFT",
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_payroll_runs",
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    total_gross = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    total_deductions = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    total_net = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    class Meta:
        ordering = ["-period", "-id"]


class PayrollEntry(TimeStampedModel):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]
    payroll_run = models.ForeignKey(
        PayrollRun,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payroll_entries",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payroll_entries",
    )
    period = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )
    basic_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    allowances = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    gross_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    deductions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    net_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        null=True,
        blank=True,
        default="PENDING",
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    # Payroll proration fields.  These allow HR to pay only the days that are
    # payable in a month, for example when an employee has approved unpaid
    # leave. Existing payroll records default to a full 30-day month.
    total_period_days = models.DecimalField(max_digits=6, decimal_places=2, default=30)
    payable_days = models.DecimalField(max_digits=6, decimal_places=2, default=30)
    unpaid_leave_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    salary_calculation_method = models.CharField(
        max_length=20,
        choices=[("FULL", "Full Salary"), ("PRORATED", "Prorated by Payable Days")],
        default="FULL",
    )

    class Meta:
        ordering = ["employee__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "period"], name="unique_employee_payroll_period"
            )
        ]
