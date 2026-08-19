from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import *

import calendar
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MONEY = Decimal("0.01")


def payroll_period_dates(period):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(period or "")):
        raise serializers.ValidationError("Period must use YYYY-MM format.")

    year, month = [int(value) for value in period.split("-")]

    return (
        date(year, month, 1),
        date(year, month, calendar.monthrange(year, month)[1]),
    )


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = "__all__"


class DesignationSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Designation
        fields = "__all__"


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    document_type_display = serializers.CharField(
        source="get_document_type_display", read_only=True
    )
    file_url = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)

    class Meta:
        model = EmployeeDocument
        fields = "__all__"
        read_only_fields = ["uploaded_by", "created_at", "updated_at"]

    def get_file_url(self, obj):
        if not obj.file:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url

    def get_uploaded_by_name(self, obj):
        if not obj.uploaded_by:
            return ""
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username

    def validate_file(self, value):
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Document must be 10 MB or smaller.")
        return value


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    total_salary = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )
    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        allow_null=True,
    )
    designation_name = serializers.CharField(
        source="designation.name",
        read_only=True,
        allow_null=True,
    )
    documents = EmployeeDocumentSerializer(many=True, read_only=True)

    DATE_FIELDS = (
        "date_of_birth",
        "joining_date",
        "passport_issue_date",
        "passport_expiry_date",
        "emirates_id_issue_date",
        "emirates_id_expiry_date",
        "visa_issue_date",
        "visa_expiry_date",
        "labor_contract_start_date",
        "labor_contract_end_date",
        "driving_license_issue_date",
        "driving_license_expiry_date",
        "insurance_issue_date",
        "insurance_expiry_date",
    )

    REQUIRED_FIELDS = (
        "first_name",
        "last_name",
        "phone",
        "nationality",
        "date_of_birth",
        "joining_date",
        "branch",
        "department",
        "designation",
        "emirates_id_number",
        "emirates_id_issue_date",
        "emirates_id_expiry_date",
        "basic_salary",
    )

    class Meta:
        model = Employee
        fields = "__all__"
        read_only_fields = [
            "employee_code",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "first_name": {"required": True, "allow_blank": False},
            "last_name": {"required": True, "allow_blank": False},
            "phone": {"required": True, "allow_blank": False},
            "nationality": {"required": True, "allow_blank": False},
            "date_of_birth": {"required": True, "allow_null": False},
            "joining_date": {"required": True, "allow_null": False},
            "branch": {"required": True, "allow_null": False},
            "department": {"required": True, "allow_null": False},
            "designation": {"required": True, "allow_null": False},
            "emirates_id_number": {"required": True, "allow_blank": False},
            "emirates_id_issue_date": {"required": True, "allow_null": False},
            "emirates_id_expiry_date": {"required": True, "allow_null": False},
            "basic_salary": {"required": True, "allow_null": False},
        }

    def to_internal_value(self, data):
        """Normalize HTML-form empty values before DRF date validation.

        Optional blank dates become ``None``. Required date fields then receive
        a clear required/null validation message instead of the generic
        "wrong format" error. Non-empty dates must use ISO ``YYYY-MM-DD``.
        """
        if hasattr(data, "copy"):
            mutable = data.copy()
        else:
            mutable = dict(data)

        for field_name in self.DATE_FIELDS:
            if field_name in mutable:
                value = mutable.get(field_name)
                if value is None or str(value).strip() == "":
                    mutable[field_name] = None
                else:
                    mutable[field_name] = str(value).strip()

        # Employee code is always generated by the backend.
        mutable.pop("employee_code", None)

        return super().to_internal_value(mutable)

    def validate(self, attrs):
        errors = {}

        # On PATCH, use current model values for fields not supplied.
        for field_name in self.REQUIRED_FIELDS:
            value = attrs.get(
                field_name,
                getattr(self.instance, field_name, None) if self.instance else None,
            )

            if value is None or (isinstance(value, str) and not value.strip()):
                errors[field_name] = "This field is required."

        department = attrs.get(
            "department",
            getattr(self.instance, "department", None) if self.instance else None,
        )
        designation = attrs.get(
            "designation",
            getattr(self.instance, "designation", None) if self.instance else None,
        )
        branch = attrs.get(
            "branch",
            getattr(self.instance, "branch", None) if self.instance else None,
        )

        if designation and department and designation.department_id:
            if designation.department_id != department.id:
                errors["designation"] = (
                    "Selected designation does not belong to the selected department."
                )

        if designation and designation.department_id and not department:
            errors["department"] = "Department is required for this designation."

        basic_salary = attrs.get(
            "basic_salary",
            getattr(self.instance, "basic_salary", None) if self.instance else None,
        )
        allowances = attrs.get(
            "allowances",
            getattr(self.instance, "allowances", 0) if self.instance else 0,
        )

        if basic_salary is not None and Decimal(basic_salary) < 0:
            errors["basic_salary"] = "Basic salary cannot be negative."

        if allowances is not None and Decimal(allowances) < 0:
            errors["allowances"] = "Allowances cannot be negative."

        date_of_birth = attrs.get(
            "date_of_birth",
            getattr(self.instance, "date_of_birth", None) if self.instance else None,
        )
        joining_date = attrs.get(
            "joining_date",
            getattr(self.instance, "joining_date", None) if self.instance else None,
        )
        emirates_issue = attrs.get(
            "emirates_id_issue_date",
            (
                getattr(self.instance, "emirates_id_issue_date", None)
                if self.instance
                else None
            ),
        )
        emirates_expiry = attrs.get(
            "emirates_id_expiry_date",
            (
                getattr(self.instance, "emirates_id_expiry_date", None)
                if self.instance
                else None
            ),
        )

        today = timezone.localdate()

        if date_of_birth and date_of_birth >= today:
            errors["date_of_birth"] = "Date of birth must be before today."

        if emirates_issue and emirates_expiry and emirates_expiry <= emirates_issue:
            errors["emirates_id_expiry_date"] = (
                "Emirates ID expiry date must be after its issue date."
            )

        passport_issue = attrs.get(
            "passport_issue_date",
            (
                getattr(self.instance, "passport_issue_date", None)
                if self.instance
                else None
            ),
        )
        passport_expiry = attrs.get(
            "passport_expiry_date",
            (
                getattr(self.instance, "passport_expiry_date", None)
                if self.instance
                else None
            ),
        )
        if passport_issue and passport_expiry and passport_expiry <= passport_issue:
            errors["passport_expiry_date"] = (
                "Passport expiry date must be after its issue date."
            )

        visa_issue = attrs.get(
            "visa_issue_date",
            getattr(self.instance, "visa_issue_date", None) if self.instance else None,
        )
        visa_expiry = attrs.get(
            "visa_expiry_date",
            getattr(self.instance, "visa_expiry_date", None) if self.instance else None,
        )
        if visa_issue and visa_expiry and visa_expiry <= visa_issue:
            errors["visa_expiry_date"] = (
                "Visa expiry date must be after its issue date."
            )

        contract_start = attrs.get(
            "labor_contract_start_date",
            (
                getattr(self.instance, "labor_contract_start_date", None)
                if self.instance
                else None
            ),
        )
        contract_end = attrs.get(
            "labor_contract_end_date",
            (
                getattr(self.instance, "labor_contract_end_date", None)
                if self.instance
                else None
            ),
        )
        if contract_start and contract_end and contract_end <= contract_start:
            errors["labor_contract_end_date"] = (
                "Contract end date must be after its start date."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    @staticmethod
    def _assign_employee_code(employee):
        """Generate a stable, unique employee code from the database ID."""
        sequence = employee.pk

        while True:
            candidate = f"EMP{sequence:05d}"
            exists = (
                Employee.objects.filter(employee_code=candidate)
                .exclude(pk=employee.pk)
                .exists()
            )

            if not exists:
                employee.employee_code = candidate
                employee.save(update_fields=["employee_code", "updated_at"])
                return employee

            sequence += 1

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("employee_code", None)
        employee = Employee.objects.create(employee_code=None, **validated_data)
        self._assign_employee_code(employee)

        request = self.context.get("request")
        approver = None
        approver_name = ""

        if request and getattr(request, "user", None) and request.user.is_authenticated:
            approver = request.user
            approver_name = request.user.get_full_name() or request.user.username

        SalaryRevision.objects.create(
            employee=employee,
            reason="JOINING",
            effective_from=employee.joining_date or timezone.localdate(),
            basic_salary=employee.basic_salary or 0,
            allowances=employee.allowances or 0,
            approved_by=approver,
            approved_by_name=approver_name,
        )
        return employee

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop("employee_code", None)
        old_basic = Decimal(instance.basic_salary or 0)
        old_allowances = Decimal(instance.allowances or 0)
        employee = super().update(instance, validated_data)

        if not employee.employee_code:
            self._assign_employee_code(employee)

        new_basic = Decimal(employee.basic_salary or 0)
        new_allowances = Decimal(employee.allowances or 0)
        salary_changed = (old_basic, old_allowances) != (new_basic, new_allowances)

        if not salary_changed:
            return employee

        request = self.context.get("request")
        approver_name = ""
        approver = None
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            approver = request.user
            approver_name = request.user.get_full_name() or request.user.username

        joining = (
            employee.salary_revisions.filter(reason="JOINING")
            .order_by("effective_from", "id")
            .first()
        )
        has_later_revision = employee.salary_revisions.exclude(
            reason="JOINING"
        ).exists()

        if (
            joining
            and not has_later_revision
            and Decimal(joining.basic_salary or 0) + Decimal(joining.allowances or 0)
            == 0
            and new_basic + new_allowances > 0
        ):
            joining.basic_salary = new_basic
            joining.allowances = new_allowances
            joining.approved_by = joining.approved_by or approver
            joining.approved_by_name = joining.approved_by_name or approver_name
            joining.save(
                update_fields=[
                    "basic_salary",
                    "allowances",
                    "approved_by",
                    "approved_by_name",
                    "updated_at",
                ]
            )
            return employee

        SalaryRevision.objects.create(
            employee=employee,
            reason="CORRECTION",
            effective_from=timezone.localdate(),
            basic_salary=new_basic,
            allowances=new_allowances,
            approved_by=approver,
            approved_by_name=approver_name,
            notes="Salary updated from employee profile.",
        )
        return employee


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    department_name = serializers.CharField(
        source="employee.department.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Attendance
        fields = "__all__"

    def validate(self, attrs):
        employee = attrs.get("employee")
        if employee and not attrs.get("branch"):
            attrs["branch"] = employee.branch
        return attrs


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = "__all__"


class LeaveBalanceSerializer(serializers.ModelSerializer):
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)
    remaining_days = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )

    class Meta:
        model = LeaveBalance
        fields = "__all__"


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = "__all__"
        read_only_fields = ["actioned_by", "actioned_at"]

    def validate(self, attrs):
        start = attrs.get("from_date")
        end = attrs.get("to_date")
        employee = attrs.get("employee")
        leave_type = attrs.get("leave_type")

        if start and end:
            if end < start:
                raise serializers.ValidationError(
                    {"to_date": "To date cannot be before from date."}
                )
            days = Decimal((end - start).days + 1)
            attrs["days"] = days

            overlap = LeaveRequest.objects.filter(
                employee=employee,
                status__in=["PENDING", "APPROVED"],
                from_date__lte=end,
                to_date__gte=start,
            )
            if self.instance:
                overlap = overlap.exclude(pk=self.instance.pk)
            if overlap.exists():
                raise serializers.ValidationError(
                    {"from_date": "Leave overlaps an existing request."}
                )

            # Leave requests may be submitted even when a paid entitlement is
            # exhausted. The approval endpoint performs the final balance check
            # and lets authorised HR users explicitly override it. Unpaid leave
            # is never restricted by the paid annual entitlement.

        if employee and not attrs.get("branch"):
            attrs["branch"] = employee.branch
        return attrs


class SalaryRevisionSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    payroll_status_display = serializers.CharField(
        source="get_payroll_status_display", read_only=True
    )
    total_salary = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    net_salary = serializers.SerializerMethodField()

    class Meta:
        model = SalaryRevision
        fields = "__all__"
        read_only_fields = ["approved_by"]

    def get_net_salary(self, obj):
        return (obj.total_salary or Decimal("0")) - (obj.deductions or Decimal("0"))

    def validate(self, attrs):
        effective_from = attrs.get("effective_from")
        effective_to = attrs.get("effective_to")
        if effective_from and effective_to and effective_to < effective_from:
            raise serializers.ValidationError(
                {"effective_to": "To date must be on or after the From date."}
            )
        if (attrs.get("deductions") or 0) > (attrs.get("basic_salary") or 0) + (
            attrs.get("allowances") or 0
        ):
            raise serializers.ValidationError(
                {"deductions": "Deductions cannot exceed gross salary."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context.get("request")
        if request:
            validated_data["approved_by"] = request.user
            validated_data.setdefault(
                "approved_by_name",
                request.user.get_full_name() or request.user.username,
            )
        revision = SalaryRevision.objects.create(**validated_data)
        # Historical records with a To date must not overwrite current salary.
        if not revision.effective_to:
            revision.employee.basic_salary = revision.basic_salary
            revision.employee.allowances = revision.allowances
            revision.employee.save(
                update_fields=["basic_salary", "allowances", "updated_at"]
            )
        return revision


class SalaryAdvanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )
    employee_code = serializers.CharField(
        source="employee.employee_code",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = SalaryAdvance
        fields = "__all__"
        read_only_fields = [
            "branch",
            "salary_at_time",
            "remaining_amount",
            "deducted_payroll_entry",
        ]

    def validate_period(self, value):
        payroll_period_dates(value)
        return value

    def validate(self, attrs):
        employee = attrs.get(
            "employee",
            getattr(self.instance, "employee", None),
        )
        period = attrs.get(
            "period",
            getattr(self.instance, "period", None),
        )
        amount = Decimal(
            str(
                attrs.get(
                    "amount",
                    getattr(self.instance, "amount", 0),
                )
                or 0
            )
        ).quantize(MONEY)

        if not employee:
            raise serializers.ValidationError({"employee": "Employee is required."})

        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Advance amount must be greater than zero."}
            )

        salary = Decimal(
            str(
                getattr(employee, "total_salary", None)
                or getattr(employee, "basic_salary", 0)
                or 0
            )
        ).quantize(MONEY)

        if salary <= 0:
            raise serializers.ValidationError(
                {
                    "employee": (
                        "The selected employee does not have " "a configured salary."
                    )
                }
            )

        if amount > salary:
            raise serializers.ValidationError(
                {
                    "amount": (
                        "Advance salary cannot exceed the "
                        "employee's current monthly salary."
                    )
                }
            )

        attrs["salary_at_time"] = salary
        attrs["branch"] = employee.branch
        attrs.setdefault("status", "PAID")
        return attrs

    def create(self, validated_data):
        validated_data["remaining_amount"] = validated_data["amount"]
        return super().create(validated_data)


class EmployeeLoanRepaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeLoanRepayment
        fields = "__all__"
        read_only_fields = [
            "loan",
            "payroll_entry",
            "employee",
            "period",
            "amount",
        ]


class EmployeeLoanSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )
    employee_code = serializers.CharField(
        source="employee.employee_code",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )
    repayments = EmployeeLoanRepaymentSerializer(
        many=True,
        read_only=True,
    )
    paid_amount = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeLoan
        fields = "__all__"
        read_only_fields = [
            "branch",
            "remaining_balance",
            "status",
            "created_by",
        ]

    def get_paid_amount(self, obj):
        amount = Decimal(obj.amount or 0)
        remaining = Decimal(obj.remaining_balance or 0)

        return max(
            Decimal("0.00"),
            amount - remaining,
        )

    def validate(self, attrs):
        amount = Decimal(
            str(
                attrs.get(
                    "amount",
                    getattr(
                        self.instance,
                        "amount",
                        0,
                    ),
                )
                or 0
            )
        )

        monthly_installment = Decimal(
            str(
                attrs.get(
                    "monthly_installment",
                    getattr(
                        self.instance,
                        "monthly_installment",
                        0,
                    ),
                )
                or 0
            )
        )

        start_period = attrs.get(
            "start_period",
            getattr(
                self.instance,
                "start_period",
                "",
            ),
        )

        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": ("Loan amount must be greater than zero.")}
            )

        if monthly_installment <= 0:
            raise serializers.ValidationError(
                {
                    "monthly_installment": (
                        "Monthly installment must be greater than zero."
                    )
                }
            )

        if not self.instance and monthly_installment > amount:
            raise serializers.ValidationError(
                {
                    "monthly_installment": (
                        "Monthly installment cannot exceed " "the loan amount."
                    )
                }
            )

        try:
            year_text, month_text = str(start_period).split("-")

            year = int(year_text)
            month = int(month_text)

            if year < 2000:
                raise ValueError

            if month < 1 or month > 12:
                raise ValueError

        except (TypeError, ValueError):
            raise serializers.ValidationError(
                {"start_period": ("Start period must use YYYY-MM format.")}
            )

        return attrs

    def create(self, validated_data):
        employee = validated_data["employee"]

        request = self.context.get("request")

        validated_data["branch"] = employee.branch

        validated_data["remaining_balance"] = validated_data["amount"]

        validated_data["status"] = "ACTIVE"

        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user

        return super().create(validated_data)


class PayrollEntrySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )
    employee_code = serializers.CharField(
        source="employee.employee_code",
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    paid_by_name = serializers.CharField(
        source="paid_by",
        read_only=True,
    )

    class Meta:
        model = PayrollEntry
        fields = "__all__"

        read_only_fields = [
            "payroll_run",
            "branch",
            "gross_salary",
            "advance_deduction",
            "net_salary",
            "balance_payable",
            "paid_at",
        ]

    def validate(self, attrs):
        instance = self.instance

        basic_salary = Decimal(
            str(
                attrs.get(
                    "basic_salary",
                    getattr(instance, "basic_salary", 0),
                )
                or 0
            )
        )

        allowances = Decimal(
            str(
                attrs.get(
                    "allowances",
                    getattr(instance, "allowances", 0),
                )
                or 0
            )
        )

        deductions = Decimal(
            str(
                attrs.get(
                    "deductions",
                    getattr(instance, "deductions", 0),
                )
                or 0
            )
        )

        if basic_salary < 0:
            raise serializers.ValidationError(
                {"basic_salary": "Basic salary cannot be negative."}
            )

        if allowances < 0:
            raise serializers.ValidationError(
                {"allowances": "Allowances cannot be negative."}
            )

        if deductions < 0:
            raise serializers.ValidationError(
                {"deductions": "Deductions cannot be negative."}
            )

        gross_salary = basic_salary + allowances

        if deductions > gross_salary:
            raise serializers.ValidationError(
                {"deductions": "Deductions cannot exceed gross salary."}
            )

        return attrs

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        basic_salary = Decimal(
            str(
                validated_data.get(
                    "basic_salary",
                    instance.basic_salary or 0,
                )
                or 0
            )
        )

        allowances = Decimal(
            str(
                validated_data.get(
                    "allowances",
                    instance.allowances or 0,
                )
                or 0
            )
        )

        deductions = Decimal(
            str(
                validated_data.get(
                    "deductions",
                    instance.deductions or 0,
                )
                or 0
            )
        )

        advance_deduction = Decimal(str(instance.advance_deduction or 0))

        gross_salary = basic_salary + allowances

        net_salary = max(
            Decimal("0.00"),
            gross_salary - deductions - advance_deduction,
        )

        validated_data["gross_salary"] = gross_salary

        validated_data["net_salary"] = net_salary

        validated_data["balance_payable"] = (
            Decimal("0.00")
            if str(instance.status or "").upper() == "PAID"
            else net_salary
        )

        payroll_entry = super().update(
            instance,
            validated_data,
        )

        payroll_run = payroll_entry.payroll_run

        if payroll_run:
            totals = payroll_run.entries.exclude(
                status="CANCELLED",
            ).aggregate(
                gross=Sum("gross_salary"),
                deductions=Sum("deductions"),
                advance=Sum("advance_deduction"),
                net=Sum("net_salary"),
            )

            payroll_run.total_gross = totals["gross"] or Decimal("0.00")

            payroll_run.total_deductions = totals["deductions"] or Decimal("0.00")

            if hasattr(
                payroll_run,
                "total_advance_deduction",
            ):
                payroll_run.total_advance_deduction = totals["advance"] or Decimal(
                    "0.00"
                )

            payroll_run.total_net = totals["net"] or Decimal("0.00")

            update_fields = [
                "total_gross",
                "total_deductions",
                "total_net",
                "updated_at",
            ]

            if hasattr(
                payroll_run,
                "total_advance_deduction",
            ):
                update_fields.append("total_advance_deduction")

            payroll_run.save(update_fields=update_fields)

        return payroll_entry


class PayrollRunSerializer(serializers.ModelSerializer):
    entries = PayrollEntrySerializer(
        many=True,
        read_only=True,
    )
    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )
    generated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = "__all__"

    def get_generated_by_name(self, obj):
        if not obj.generated_by:
            return ""
        return (
            obj.generated_by.get_full_name()
            or obj.generated_by.username
            or obj.generated_by.email
        )


class SalaryCertificateSerializer(serializers.ModelSerializer):
    total_monthly_salary = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )

    branch_id = serializers.IntegerField(
        source="employee.branch_id",
        read_only=True,
    )

    branch_name = serializers.SerializerMethodField()

    issued_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SalaryCertificate
        fields = "__all__"

        read_only_fields = [
            "reference_number",
            "employee_name",
            "employee_code",
            "designation_name",
            "joining_date",
            "issued_by",
            "created_at",
            "updated_at",
        ]

    def get_branch_name(self, obj):
        branch = getattr(
            obj.employee,
            "branch",
            None,
        )

        if not branch:
            return None

        return (
            getattr(
                branch,
                "branch_name",
                None,
            )
            or getattr(
                branch,
                "name",
                None,
            )
            or str(branch)
        )

    def get_issued_by_name(self, obj):
        user = obj.issued_by

        if not user:
            return None

        return (
            getattr(
                user,
                "full_name",
                None,
            )
            or getattr(
                user,
                "name",
                None,
            )
            or getattr(
                user,
                "email",
                None,
            )
            or str(user)
        )

    def validate_employee(self, employee):
        allowed_statuses = {
            "ACTIVE",
            "PROBATION",
            "ON_LEAVE",
        }

        if employee.employment_status not in allowed_statuses:
            raise serializers.ValidationError(
                "Salary certificates can only be issued "
                "for currently employed employees."
            )

        return employee

    def validate(self, attrs):
        for field_name in [
            "basic_salary",
            "housing_allowance",
            "transport_other_allowance",
        ]:
            value = Decimal(
                str(
                    attrs.get(
                        field_name,
                        getattr(
                            self.instance,
                            field_name,
                            0,
                        ),
                    )
                    or 0
                )
            )

            if value < 0:
                raise serializers.ValidationError(
                    {field_name: ("Salary amount cannot be negative.")}
                )

        # signatory = str(
        #     attrs.get(
        #         "authorized_signatory",
        #         getattr(
        #             self.instance,
        #             "authorized_signatory",
        #             "",
        #         ),
        #     )
        #     or ""
        # ).strip()

        # signatory_designation = str(
        #     attrs.get(
        #         "signatory_designation",
        #         getattr(
        #             self.instance,
        #             "signatory_designation",
        #             "",
        #         ),
        #     )
        #     or ""
        # ).strip()

        # if not signatory:
        #     raise serializers.ValidationError(
        #         {"authorized_signatory": ("Authorized signatory is required.")}
        #     )

        # if not signatory_designation:
        #     raise serializers.ValidationError(
        #         {"signatory_designation": ("Signatory designation is required.")}
        #     )

        return attrs

    def _generate_reference_number(self):
        prefix = timezone.localdate().strftime("SC-%Y%m")

        latest = (
            SalaryCertificate.objects.filter(reference_number__startswith=prefix)
            .order_by("-id")
            .first()
        )

        next_number = 1

        if latest:
            try:
                next_number = (
                    int(
                        latest.reference_number.rsplit(
                            "-",
                            1,
                        )[-1]
                    )
                    + 1
                )
            except (
                TypeError,
                ValueError,
            ):
                next_number = (
                    SalaryCertificate.objects.filter(
                        reference_number__startswith=prefix
                    ).count()
                    + 1
                )

        return f"{prefix}-{next_number:04d}"

    @transaction.atomic
    def create(
        self,
        validated_data,
    ):
        employee = validated_data["employee"]

        request = self.context.get("request")

        supplied_identity = str(validated_data.get("identity_number") or "").strip()

        identity_number = (
            supplied_identity
            or employee.passport_number
            or employee.emirates_id_number
            or ""
        )

        validated_data.update(
            {
                "reference_number": (self._generate_reference_number()),
                "employee_name": (employee.full_name),
                "employee_code": (employee.employee_code or ""),
                "identity_number": (identity_number),
                "designation_name": (
                    employee.designation.name if employee.designation else ""
                ),
                "joining_date": (employee.joining_date),
                "issued_by": (
                    request.user if request and request.user.is_authenticated else None
                ),
            }
        )

        return super().create(validated_data)


class EmployeeLetterSerializer(serializers.ModelSerializer):
    branch_id = serializers.IntegerField(
        source="employee.branch_id",
        read_only=True,
    )
    branch_name = serializers.SerializerMethodField()
    issued_by_name = serializers.SerializerMethodField()
    letter_type_display = serializers.CharField(
        source="get_letter_type_display",
        read_only=True,
    )

    class Meta:
        model = EmployeeLetter
        fields = "__all__"
        read_only_fields = [
            "reference_number",
            "employee_name",
            "employee_code",
            "designation_name",
            "department_name",
            "joining_date",
            "issued_by",
            "created_at",
            "updated_at",
        ]

    def get_branch_name(self, obj):
        branch = getattr(obj.employee, "branch", None)
        if not branch:
            return None
        return (
            getattr(branch, "branch_name", None)
            or getattr(branch, "name", None)
            or str(branch)
        )

    def get_issued_by_name(self, obj):
        user = obj.issued_by
        if not user:
            return None
        return (
            getattr(user, "full_name", None)
            or getattr(user, "name", None)
            or getattr(user, "email", None)
            or getattr(user, "username", None)
            or str(user)
        )

    def validate(self, attrs):
        letter_type = attrs.get(
            "letter_type",
            getattr(self.instance, "letter_type", None),
        )
        employee = attrs.get(
            "employee",
            getattr(self.instance, "employee", None),
        )

        # signatory = str(
        #     attrs.get(
        #         "authorized_signatory",
        #         getattr(self.instance, "authorized_signatory", ""),
        #     )
        #     or ""
        # ).strip()

        # signatory_designation = str(
        #     attrs.get(
        #         "signatory_designation",
        #         getattr(self.instance, "signatory_designation", ""),
        #     )
        #     or ""
        # ).strip()

        # if not signatory:
        #     raise serializers.ValidationError(
        #         {"authorized_signatory": "Authorized signatory is required."}
        #     )

        # if not signatory_designation:
        #     raise serializers.ValidationError(
        #         {"signatory_designation": "Signatory designation is required."}
        #     )

        if letter_type == "WARNING":
            reason = str(
                attrs.get(
                    "reason",
                    getattr(self.instance, "reason", ""),
                )
                or ""
            ).strip()

            if not reason:
                raise serializers.ValidationError(
                    {"reason": "Reason is required for a warning letter."}
                )

            allowed_statuses = {
                "ACTIVE",
                "PROBATION",
                "ON_LEAVE",
            }

            if employee and employee.employment_status not in allowed_statuses:
                raise serializers.ValidationError(
                    {
                        "employee": (
                            "Warning letters can only be issued to a "
                            "currently employed employee."
                        )
                    }
                )

        if letter_type == "EXPERIENCE":
            last_working_date = attrs.get(
                "last_working_date",
                getattr(self.instance, "last_working_date", None),
            )

            if not last_working_date:
                raise serializers.ValidationError(
                    {
                        "last_working_date": (
                            "Last working date is required for an " "experience letter."
                        )
                    }
                )

            if employee and employee.joining_date:
                if last_working_date < employee.joining_date:
                    raise serializers.ValidationError(
                        {
                            "last_working_date": (
                                "Last working date cannot be before "
                                "the employee joining date."
                            )
                        }
                    )

        return attrs

    def _generate_reference_number(self, letter_type):
        prefix_code = "WL" if letter_type == "WARNING" else "EL"
        prefix = timezone.localdate().strftime(f"{prefix_code}-%Y%m")

        latest = (
            EmployeeLetter.objects.filter(reference_number__startswith=prefix)
            .order_by("-id")
            .first()
        )

        next_number = 1

        if latest:
            try:
                next_number = int(latest.reference_number.rsplit("-", 1)[-1]) + 1
            except (TypeError, ValueError):
                next_number = (
                    EmployeeLetter.objects.filter(
                        reference_number__startswith=prefix
                    ).count()
                    + 1
                )

        return f"{prefix}-{next_number:04d}"

    @transaction.atomic
    def create(self, validated_data):
        employee = validated_data["employee"]
        letter_type = validated_data["letter_type"]
        request = self.context.get("request")

        validated_data.update(
            {
                "reference_number": self._generate_reference_number(letter_type),
                "employee_name": employee.full_name,
                "employee_code": employee.employee_code or "",
                "designation_name": (
                    employee.designation.name if employee.designation else ""
                ),
                "department_name": (
                    employee.department.name if employee.department else ""
                ),
                "joining_date": employee.joining_date,
                "issued_by": (
                    request.user if request and request.user.is_authenticated else None
                ),
            }
        )

        if letter_type == "WARNING":
            validated_data["last_working_date"] = None
            validated_data["experience_summary"] = ""
            validated_data["conduct_note"] = ""

        if letter_type == "EXPERIENCE":
            validated_data["subject"] = ""
            validated_data["reason"] = ""
            validated_data["details"] = ""

        return super().create(validated_data)
