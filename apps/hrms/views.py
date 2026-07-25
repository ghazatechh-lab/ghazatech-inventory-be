import csv
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import *
from .serializers import *


class BaseViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]


class DepartmentViewSet(BaseViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    search_fields = ["name", "code"]
    filterset_fields = ["is_active"]


class DesignationViewSet(BaseViewSet):
    queryset = Designation.objects.select_related("department")
    serializer_class = DesignationSerializer
    search_fields = ["name", "department__name"]
    filterset_fields = ["department", "is_active"]


class EmployeeViewSet(BaseViewSet):
    queryset = Employee.objects.select_related(
        "branch", "department", "designation"
    ).prefetch_related("documents", "salary_revisions")
    serializer_class = EmployeeSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = [
        "employee_code",
        "first_name",
        "last_name",
        "email",
        "phone",
        "passport_number",
        "emirates_id_number",
        "visa_number",
        "labor_contract_number",
    ]
    filterset_fields = [
        "branch",
        "department",
        "designation",
        "employment_status",
        "employment_type",
        "is_active",
    ]
    ordering_fields = [
        "employee_code",
        "first_name",
        "joining_date",
        "basic_salary",
        "employment_status",
        "created_at",
    ]

    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        from apps.branches.models import Branch

        return Response(
            {
                "branches": [
                    {"id": item.id, "branch_name": item.branch_name}
                    for item in Branch.objects.filter(is_active=True).order_by(
                        "branch_name"
                    )
                ],
                "departments": DepartmentSerializer(
                    Department.objects.filter(is_active=True), many=True
                ).data,
                "designations": DesignationSerializer(
                    Designation.objects.filter(is_active=True).select_related(
                        "department"
                    ),
                    many=True,
                ).data,
            }
        )

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
        url_path="documents",
    )
    def upload_document(self, request, pk=None):
        employee = self.get_object()
        serializer = EmployeeDocumentSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(employee=employee, uploaded_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="salary-history")
    def salary_history(self, request, pk=None):
        employee = self.get_object()
        return Response(
            SalaryRevisionSerializer(employee.salary_revisions.all(), many=True).data
        )

    @action(detail=True, methods=["post"], url_path="salary-revisions")
    def salary_revisions(self, request, pk=None):
        data = request.data.copy()
        data["employee"] = self.get_object().id
        serializer = SalaryRevisionSerializer(
            data=data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class EmployeeDocumentViewSet(BaseViewSet):
    queryset = EmployeeDocument.objects.select_related("employee", "uploaded_by")
    serializer_class = EmployeeDocumentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = [
        "title",
        "document_number",
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
    ]
    filterset_fields = ["employee", "document_type"]


class AttendanceViewSet(BaseViewSet):
    queryset = Attendance.objects.select_related(
        "employee", "employee__department", "branch"
    )
    serializer_class = AttendanceSerializer
    search_fields = [
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
        "remarks",
    ]
    filterset_fields = [
        "employee",
        "branch",
        "status",
        "date",
        "employee__department",
    ]
    ordering = ["-date", "employee__first_name"]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        today_records = self.filter_queryset(self.get_queryset()).filter(
            date=timezone.localdate()
        )

        return Response(
            {
                "present": today_records.filter(status="PRESENT").count(),
                "absent": today_records.filter(status="ABSENT").count(),
                "late": today_records.filter(status="LATE").count(),
                "on_leave": today_records.filter(status="LEAVE").count(),
                "overtime_hours": (
                    today_records.aggregate(value=Sum("overtime_hours"))["value"] or 0
                ),
            }
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        export_format = request.query_params.get("format", "csv").lower()

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        headers = [
            "Employee Code",
            "Employee",
            "Branch",
            "Department",
            "Date",
            "Check In",
            "Check Out",
            "Status",
            "Working Hours",
            "Overtime Hours",
            "Remarks",
        ]
        rows = [
            [
                item.employee.employee_code,
                item.employee.full_name,
                item.branch.branch_name if item.branch else "",
                item.employee.department.name if item.employee.department else "",
                item.date,
                item.check_in or "",
                item.check_out or "",
                item.get_status_display(),
                item.working_hours or 0,
                item.overtime_hours or 0,
                item.remarks or "",
            ]
            for item in queryset
        ]

        if export_format == "xlsx":
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Font
            except ImportError:
                return Response(
                    {"detail": "Install openpyxl to export Excel attendance sheets."},
                    status=status.HTTP_501_NOT_IMPLEMENTED,
                )

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Attendance"
            sheet.append(headers)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for row in rows:
                sheet.append(row)

            buffer = BytesIO()
            workbook.save(buffer)
            response = HttpResponse(
                buffer.getvalue(),
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )
            response["Content-Disposition"] = (
                'attachment; filename="attendance-sheet.xlsx"'
            )
            return response

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="attendance-sheet.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(rows)
        return response


class LeaveTypeViewSet(BaseViewSet):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    filterset_fields = ["is_active", "is_paid"]


class LeaveBalanceViewSet(BaseViewSet):
    queryset = LeaveBalance.objects.select_related("employee", "leave_type")
    serializer_class = LeaveBalanceSerializer
    filterset_fields = ["employee", "leave_type", "year"]


class LeaveRequestViewSet(BaseViewSet):
    queryset = LeaveRequest.objects.select_related(
        "employee", "branch", "leave_type", "actioned_by"
    )
    serializer_class = LeaveRequestSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    search_fields = [
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
        "reason",
    ]
    filterset_fields = [
        "employee",
        "branch",
        "leave_type",
        "status",
        "from_date",
        "to_date",
    ]
    ordering = ["-created_at"]

    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        employees = Employee.objects.filter(
            is_active=True,
            employment_status__in=["ACTIVE", "ON_LEAVE", "PROBATION"],
        ).select_related("branch")

        return Response(
            {
                "employees": [
                    {
                        "id": item.id,
                        "employee_code": item.employee_code,
                        "full_name": item.full_name,
                        "branch_id": item.branch_id,
                        "branch_name": item.branch.branch_name if item.branch else "",
                    }
                    for item in employees
                ],
                "leave_types": LeaveTypeSerializer(
                    LeaveType.objects.filter(is_active=True), many=True
                ).data,
            }
        )

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        leave = self.get_object()
        if leave.status != "PENDING":
            return Response(
                {"detail": "Only pending requests can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        balance, _ = LeaveBalance.objects.get_or_create(
            employee=leave.employee,
            leave_type=leave.leave_type,
            year=leave.from_date.year,
            defaults={"entitled_days": leave.leave_type.annual_limit},
        )
        if leave.days > balance.remaining_days:
            return Response(
                {"detail": f"Only {balance.remaining_days} day(s) available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        balance.used_days += leave.days
        balance.save(update_fields=["used_days", "updated_at"])

        leave.status = "APPROVED"
        leave.action_remarks = request.data.get("remarks", "")
        leave.actioned_by = request.user
        leave.actioned_at = timezone.now()
        leave.save(
            update_fields=[
                "status",
                "action_remarks",
                "actioned_by",
                "actioned_at",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(leave).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        leave = self.get_object()
        if leave.status != "PENDING":
            return Response(
                {"detail": "Only pending requests can be rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        leave.status = "REJECTED"
        leave.action_remarks = request.data.get("remarks", "")
        leave.actioned_by = request.user
        leave.actioned_at = timezone.now()
        leave.save(
            update_fields=[
                "status",
                "action_remarks",
                "actioned_by",
                "actioned_at",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(leave).data)


class SalaryRevisionViewSet(BaseViewSet):
    queryset = SalaryRevision.objects.select_related("employee", "approved_by")
    serializer_class = SalaryRevisionSerializer
    filterset_fields = ["employee", "reason", "effective_from"]


class PayrollRunViewSet(BaseViewSet):
    queryset = PayrollRun.objects.select_related(
        "branch", "generated_by"
    ).prefetch_related("entries__employee", "entries__branch")
    serializer_class = PayrollRunSerializer
    filterset_fields = ["period", "branch", "status"]

    @action(detail=False, methods=["get"], url_path="eligible-employees")
    def eligible_employees(self, request):
        period = request.query_params.get("period")
        branch_id = request.query_params.get("branch")

        employees = Employee.objects.filter(
            is_active=True,
            employment_status__in=["ACTIVE", "ON_LEAVE", "PROBATION"],
        ).select_related("branch", "department")

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        used_ids = set(
            PayrollEntry.objects.filter(period=period).values_list(
                "employee_id", flat=True
            )
        )

        return Response(
            [
                {
                    "id": item.id,
                    "employee_code": item.employee_code,
                    "full_name": item.full_name,
                    "branch_name": item.branch.branch_name if item.branch else "",
                    "basic_salary": item.basic_salary,
                    "allowances": item.allowances,
                    "gross_salary": item.total_salary,
                    "already_paid": item.id in used_ids,
                }
                for item in employees
            ]
        )

    @transaction.atomic
    @action(detail=False, methods=["post"])
    def generate(self, request):
        period = request.data.get("period")
        branch_id = request.data.get("branch")
        employee_ids = request.data.get("employee_ids", [])

        employees = Employee.objects.filter(
            id__in=employee_ids,
            is_active=True,
        ).select_related("branch")

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        employees = employees.exclude(
            id__in=PayrollEntry.objects.filter(period=period).values_list(
                "employee_id", flat=True
            )
        )

        if not period or not employees.exists():
            return Response(
                {"detail": "Select a pay period and eligible employees."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        run = PayrollRun.objects.create(
            period=period,
            branch_id=branch_id or None,
            status="PROCESSING",
            generated_by=request.user,
            generated_at=timezone.now(),
        )

        gross_total = Decimal("0")
        deduction_total = Decimal("0")
        net_total = Decimal("0")

        for employee in employees:
            gross = employee.total_salary
            deductions = Decimal("0")
            net = gross - deductions

            PayrollEntry.objects.create(
                payroll_run=run,
                employee=employee,
                branch=employee.branch,
                period=period,
                basic_salary=employee.basic_salary or 0,
                allowances=employee.allowances or 0,
                gross_salary=gross,
                deductions=deductions,
                net_salary=net,
                status="PENDING",
            )
            gross_total += gross
            deduction_total += deductions
            net_total += net

        run.total_gross = gross_total
        run.total_deductions = deduction_total
        run.total_net = net_total
        run.status = "COMPLETED"
        run.save(
            update_fields=[
                "total_gross",
                "total_deductions",
                "total_net",
                "status",
                "updated_at",
            ]
        )

        return Response(
            self.get_serializer(run).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        entries = PayrollEntry.objects.all()
        period = request.query_params.get("period")
        branch_id = request.query_params.get("branch")

        if period:
            entries = entries.filter(period=period)
        if branch_id:
            entries = entries.filter(branch_id=branch_id)

        totals = entries.aggregate(
            gross=Sum("gross_salary"),
            deductions=Sum("deductions"),
            net=Sum("net_salary"),
        )

        return Response(
            {
                "employees_on_payroll": entries.count(),
                "total_gross": totals["gross"] or 0,
                "total_deductions": totals["deductions"] or 0,
                "total_net": totals["net"] or 0,
            }
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        entries = PayrollEntry.objects.select_related("employee", "branch")
        period = request.query_params.get("period")
        branch_id = request.query_params.get("branch")
        if period:
            entries = entries.filter(period=period)
        if branch_id:
            entries = entries.filter(branch_id=branch_id)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="payroll.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Employee Code",
                "Employee",
                "Branch",
                "Period",
                "Basic",
                "Allowances",
                "Gross",
                "Deductions",
                "Net",
                "Status",
            ]
        )
        for item in entries:
            writer.writerow(
                [
                    item.employee.employee_code,
                    item.employee.full_name,
                    item.branch.branch_name if item.branch else "",
                    item.period,
                    item.basic_salary,
                    item.allowances,
                    item.gross_salary,
                    item.deductions,
                    item.net_salary,
                    item.get_status_display(),
                ]
            )
        return response


class PayrollEntryViewSet(BaseViewSet):
    queryset = PayrollEntry.objects.select_related("employee", "branch", "payroll_run")
    serializer_class = PayrollEntrySerializer
    search_fields = [
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
        "period",
    ]
    filterset_fields = ["period", "branch", "status", "employee"]


class DocumentExpiryViewSet(BaseViewSet):
    queryset = EmployeeDocument.objects.select_related(
        "employee", "employee__branch", "uploaded_by"
    )
    serializer_class = EmployeeDocumentSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset().filter(expiry_date__isnull=False)
        days = int(self.request.query_params.get("days", 90))
        branch_id = self.request.query_params.get("branch")
        queryset = queryset.filter(
            expiry_date__lte=timezone.localdate() + timedelta(days=days)
        )
        if branch_id:
            queryset = queryset.filter(employee__branch_id=branch_id)
        return queryset.order_by("expiry_date")


class HRMSReportViewSet(BaseViewSet):
    queryset = Employee.objects.none()
    serializer_class = EmployeeSerializer
    http_method_names = ["get", "head", "options"]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        today = timezone.localdate()
        return Response(
            {
                "employees": Employee.objects.filter(is_active=True).count(),
                "present_today": Attendance.objects.filter(
                    date=today, status="PRESENT"
                ).count(),
                "pending_leaves": LeaveRequest.objects.filter(status="PENDING").count(),
                "payroll_net": (
                    PayrollEntry.objects.filter(
                        period=today.strftime("%Y-%m")
                    ).aggregate(value=Sum("net_salary"))["value"]
                    or 0
                ),
            }
        )

    @action(detail=False, methods=["get"])
    def export(self, request):
        report_type = request.query_params.get("report_type", "EMPLOYEE")
        branch_id = request.query_params.get("branch")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="hrms-{report_type.lower()}-report.csv"'
        )
        writer = csv.writer(response)

        if report_type == "ATTENDANCE":
            queryset = Attendance.objects.select_related("employee", "branch")
            if branch_id:
                queryset = queryset.filter(branch_id=branch_id)
            if start_date:
                queryset = queryset.filter(date__gte=start_date)
            if end_date:
                queryset = queryset.filter(date__lte=end_date)

            writer.writerow(
                [
                    "Employee Code",
                    "Employee",
                    "Branch",
                    "Date",
                    "Status",
                    "Check In",
                    "Check Out",
                    "Working Hours",
                    "Overtime Hours",
                ]
            )
            for item in queryset:
                writer.writerow(
                    [
                        item.employee.employee_code,
                        item.employee.full_name,
                        item.branch.branch_name if item.branch else "",
                        item.date,
                        item.get_status_display(),
                        item.check_in or "",
                        item.check_out or "",
                        item.working_hours,
                        item.overtime_hours,
                    ]
                )
            return response

        if report_type == "LEAVE":
            queryset = LeaveRequest.objects.select_related(
                "employee", "leave_type", "branch"
            )
            if branch_id:
                queryset = queryset.filter(branch_id=branch_id)
            writer.writerow(
                [
                    "Employee Code",
                    "Employee",
                    "Leave Type",
                    "From",
                    "To",
                    "Days",
                    "Reason",
                    "Status",
                ]
            )
            for item in queryset:
                writer.writerow(
                    [
                        item.employee.employee_code,
                        item.employee.full_name,
                        item.leave_type.name,
                        item.from_date,
                        item.to_date,
                        item.days,
                        item.reason,
                        item.get_status_display(),
                    ]
                )
            return response

        if report_type == "PAYROLL":
            queryset = PayrollEntry.objects.select_related("employee", "branch")
            if branch_id:
                queryset = queryset.filter(branch_id=branch_id)
            writer.writerow(
                [
                    "Employee Code",
                    "Employee",
                    "Branch",
                    "Period",
                    "Gross",
                    "Deductions",
                    "Net",
                    "Status",
                ]
            )
            for item in queryset:
                writer.writerow(
                    [
                        item.employee.employee_code,
                        item.employee.full_name,
                        item.branch.branch_name if item.branch else "",
                        item.period,
                        item.gross_salary,
                        item.deductions,
                        item.net_salary,
                        item.get_status_display(),
                    ]
                )
            return response

        queryset = Employee.objects.select_related(
            "branch", "department", "designation"
        )
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        writer.writerow(
            [
                "Employee Code",
                "Employee",
                "Branch",
                "Department",
                "Designation",
                "Email",
                "Phone",
                "Nationality",
                "Passport Number",
                "Passport Expiry",
                "Emirates ID",
                "Emirates ID Expiry",
                "Visa Number",
                "Visa Expiry",
                "Labor Contract",
                "Contract End",
                "Basic Salary",
                "Allowances",
                "Status",
            ]
        )
        for item in queryset:
            writer.writerow(
                [
                    item.employee_code,
                    item.full_name,
                    item.branch.branch_name if item.branch else "",
                    item.department.name if item.department else "",
                    item.designation.name if item.designation else "",
                    item.email or "",
                    item.phone or "",
                    item.nationality or "",
                    item.passport_number or "",
                    item.passport_expiry_date or "",
                    item.emirates_id_number or "",
                    item.emirates_id_expiry_date or "",
                    item.visa_number or "",
                    item.visa_expiry_date or "",
                    item.labor_contract_number or "",
                    item.labor_contract_end_date or "",
                    item.basic_salary,
                    item.allowances,
                    item.get_employment_status_display(),
                ]
            )
        return response
