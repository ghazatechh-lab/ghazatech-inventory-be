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
        max_digits=14, decimal_places=2, read_only=True
    )
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, allow_null=True
    )
    designation_name = serializers.CharField(
        source="designation.name", read_only=True, allow_null=True
    )
    documents = EmployeeDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Employee
        fields = "__all__"

    @transaction.atomic
    def create(self, validated_data):
        employee = Employee.objects.create(**validated_data)
        request = self.context.get("request")
        SalaryRevision.objects.create(
            employee=employee,
            reason="JOINING",
            effective_from=employee.joining_date or timezone.localdate(),
            basic_salary=employee.basic_salary or 0,
            allowances=employee.allowances or 0,
            approved_by=request.user if request else None,
            approved_by_name=(
                request.user.get_full_name() or request.user.username if request else ""
            ),
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
    total_salary = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = SalaryRevision
        fields = "__all__"
        read_only_fields = ["approved_by"]

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
