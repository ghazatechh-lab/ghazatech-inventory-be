from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import *


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

            balance = LeaveBalance.objects.filter(
                employee=employee, leave_type=leave_type, year=start.year
            ).first()
            if balance and days > balance.remaining_days:
                raise serializers.ValidationError(
                    {"days": f"Only {balance.remaining_days} day(s) available."}
                )

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


class PayrollEntrySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True
    )
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )

    class Meta:
        model = PayrollEntry
        fields = "__all__"


class PayrollRunSerializer(serializers.ModelSerializer):
    entries = PayrollEntrySerializer(many=True, read_only=True)

    class Meta:
        model = PayrollRun
        fields = "__all__"
        read_only_fields = [
            "generated_by",
            "generated_at",
            "total_gross",
            "total_deductions",
            "total_net",
        ]
