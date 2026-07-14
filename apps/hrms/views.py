from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from django.utils import timezone
from .models import *
from .serializers import *
from apps.common.response import ok
from datetime import timedelta

from django.db import models
from rest_framework.decorators import api_view


class Generic(ModelViewSet):
    def perform_create(self, s):
        s.save()


class EmployeeViewSet(Generic):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    search_fields = [
        "employee_code",
        "first_name",
        "last_name",
        "passport_number",
        "emirates_id_number",
    ]
    filterset_fields = ["branch", "department", "designation", "status"]

    @action(detail=True, methods=["get", "post"])
    def documents(self, r, pk=None):
        if r.method == "GET":
            return ok(
                EmployeeDocumentSerializer(
                    self.get_object().documents.all(), many=True
                ).data
            )
        d = r.data.copy()
        d["employee"] = pk
        s = EmployeeDocumentSerializer(data=d)
        s.is_valid(raise_exception=True)
        s.save()
        return ok(s.data, "Document created", 201)


class AttendanceViewSet(Generic):
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    filterset_fields = ["employee", "branch", "attendance_date", "attendance_status"]


class LeaveViewSet(Generic):
    queryset = LeaveRequest.objects.all()
    serializer_class = LeaveRequestSerializer
    filterset_fields = ["employee", "leave_type", "status"]

    @action(detail=True, methods=["post"])
    def approve(self, r, pk=None):
        o = self.get_object()
        o.status = "APPROVED"
        o.approved_by = r.user
        o.save()
        return ok(LeaveRequestSerializer(o).data, "Leave approved")

    @action(detail=True, methods=["post"])
    def reject(self, r, pk=None):
        o = self.get_object()
        o.status = "REJECTED"
        o.approved_by = r.user
        o.approval_remarks = r.data.get("remarks", "")
        o.save()
        return ok(LeaveRequestSerializer(o).data, "Leave rejected")


class PayrollViewSet(Generic):
    queryset = Payroll.objects.all()
    serializer_class = PayrollSerializer
    filterset_fields = ["employee", "branch", "payment_status", "payroll_month"]


class DepartmentViewSet(Generic):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer


class DesignationViewSet(Generic):
    queryset = Designation.objects.all()
    serializer_class = DesignationSerializer


class LeaveTypeViewSet(Generic):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer


@api_view(["GET"])
def document_expiry(request):
    today = timezone.localdate()
    days = int(request.query_params.get("days", 60))
    upcoming_date = today + timedelta(days=days)

    employees = Employee.objects.select_related(
        "branch",
        "department",
        "designation",
    ).filter(
        models.Q(passport_expiry_date__lte=upcoming_date)
        | models.Q(visa_expiry_date__lte=upcoming_date)
        | models.Q(emirates_id_expiry_date__lte=upcoming_date)
        | models.Q(labour_card_expiry_date__lte=upcoming_date)
        | models.Q(driving_license_expiry_date__lte=upcoming_date)
        | models.Q(insurance_expiry_date__lte=upcoming_date)
    )

    branch_id = request.query_params.get("branch")
    if branch_id:
        employees = employees.filter(branch_id=branch_id)

    data = []

    document_fields = [
        ("Passport", "passport_number", "passport_expiry_date"),
        ("Visa", "visa_number", "visa_expiry_date"),
        ("Emirates ID", "emirates_id_number", "emirates_id_expiry_date"),
        ("Labour Card", "labour_card_number", "labour_card_expiry_date"),
        ("Driving License", "driving_license_number", "driving_license_expiry_date"),
        ("Medical Insurance", "insurance_policy_number", "insurance_expiry_date"),
    ]

    for employee in employees:
        for document_type, number_field, expiry_field in document_fields:
            expiry_date = getattr(employee, expiry_field)

            if not expiry_date:
                continue

            if expiry_date > upcoming_date:
                continue

            days_remaining = (expiry_date - today).days

            if days_remaining < 0:
                status = "Expired"
            elif days_remaining <= 7:
                status = "Expiring within 7 days"
            elif days_remaining <= 30:
                status = "Expiring within 30 days"
            else:
                status = "Expiring within 60 days"

            data.append(
                {
                    "employee_id": employee.id,
                    "employee_code": employee.employee_code,
                    "employee_name": employee.full_name,
                    "branch": employee.branch.branch_name if employee.branch else None,
                    "department": (
                        employee.department.name if employee.department else None
                    ),
                    "designation": (
                        employee.designation.title if employee.designation else None
                    ),
                    "document_type": document_type,
                    "document_number": getattr(employee, number_field),
                    "expiry_date": expiry_date,
                    "days_remaining": days_remaining,
                    "status": status,
                }
            )

    data = sorted(data, key=lambda item: item["expiry_date"])

    return ok(data, message="Employee document expiry fetched successfully")
