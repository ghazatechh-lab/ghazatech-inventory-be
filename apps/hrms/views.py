import calendar
import csv
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
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

    @action(detail=True, methods=["get"], url_path="profile")
    def profile(self, request, pk=None):
        employee = self.get_object()
        attendance = employee.attendance_records.select_related("branch").order_by(
            "-date"
        )
        leaves = employee.leave_requests.select_related(
            "leave_type", "actioned_by"
        ).order_by("-created_at")
        payroll = employee.payroll_entries.select_related(
            "branch", "payroll_run"
        ).order_by("-period", "-id")
        balances = employee.leave_balances.select_related("leave_type").order_by(
            "leave_type__name"
        )

        attendance_summary = {
            "present": attendance.filter(status="PRESENT").count(),
            "absent": attendance.filter(status="ABSENT").count(),
            "late": attendance.filter(status="LATE").count(),
            "leave": attendance.filter(status="LEAVE").count(),
            "half_day": attendance.filter(status="HALF_DAY").count(),
            "total_records": attendance.count(),
        }

        current_year = timezone.localdate().year
        approved_this_year = leaves.filter(
            status="APPROVED",
            from_date__year=current_year,
        )
        used_this_year = approved_this_year.aggregate(total=Sum("days"))["total"] or 0
        unpaid_days_taken = (
            approved_this_year.filter(
                leave_type__is_paid=False,
            ).aggregate(
                total=Sum("days")
            )["total"]
            or 0
        )

        annual_balance = balances.filter(
            leave_type__name__icontains="annual",
        ).first()
        sick_balance = balances.filter(
            leave_type__name__icontains="sick",
        ).first()

        leave_summary = {
            "annual_leave_left": getattr(annual_balance, "remaining_days", 0) or 0,
            "sick_leave_left": getattr(sick_balance, "remaining_days", 0) or 0,
            "used_this_year": used_this_year,
            "unpaid_days_taken": unpaid_days_taken,
            "pending_requests": leaves.filter(status="PENDING").count(),
            "approved_requests": leaves.filter(status="APPROVED").count(),
        }

        return Response(
            {
                "employee": EmployeeSerializer(
                    employee, context={"request": request}
                ).data,
                "attendance_summary": attendance_summary,
                "leave_summary": leave_summary,
                "attendance": AttendanceSerializer(attendance[:50], many=True).data,
                "leaves": LeaveRequestSerializer(leaves[:50], many=True).data,
                "leave_balances": LeaveBalanceSerializer(balances, many=True).data,
                "payroll": PayrollEntrySerializer(payroll[:36], many=True).data,
                "salary_history": SalaryRevisionSerializer(
                    employee.salary_revisions.all(),
                    many=True,
                    context={"request": request},
                ).data,
                "documents": EmployeeDocumentSerializer(
                    employee.documents.all(), many=True, context={"request": request}
                ).data,
            }
        )

    @action(detail=True, methods=["get"], url_path="salary-history")
    def salary_history(self, request, pk=None):
        employee = self.get_object()
        revisions = employee.salary_revisions.all()

        # Repair legacy data where the employee was created with zero salary and
        # the actual salary was added later without a salary revision. This is
        # only applied when there is no later revision, so genuine history is
        # never overwritten.
        joining = (
            revisions.filter(reason="JOINING").order_by("effective_from", "id").first()
        )
        has_later_revision = revisions.exclude(reason="JOINING").exists()
        employee_total = Decimal(employee.basic_salary or 0) + Decimal(
            employee.allowances or 0
        )

        if (
            joining
            and not has_later_revision
            and Decimal(joining.basic_salary or 0) + Decimal(joining.allowances or 0)
            == 0
            and employee_total > 0
        ):
            joining.basic_salary = employee.basic_salary or 0
            joining.allowances = employee.allowances or 0
            joining.save(update_fields=["basic_salary", "allowances", "updated_at"])

        return Response(
            SalaryRevisionSerializer(
                employee.salary_revisions.all(),
                many=True,
                context={"request": request},
            ).data
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
            defaults={"entitled_days": leave.leave_type.annual_limit or 0},
        )

        # Unpaid leave is not restricted by the paid annual entitlement.
        # For paid leave, HR/Admin may explicitly override the balance when
        # business approval has already been obtained.
        override_balance = str(request.data.get("override_balance", "")).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (
            leave.leave_type.is_paid
            and leave.days > balance.remaining_days
            and not override_balance
        ):
            return Response(
                {
                    "detail": f"Only {balance.remaining_days} paid day(s) are available.",
                    "code": "INSUFFICIENT_LEAVE_BALANCE",
                    "remaining_days": balance.remaining_days,
                    "requested_days": leave.days,
                    "can_override": True,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if leave.leave_type.is_paid:
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
    @staticmethod
    def _approved_unpaid_leave_days(employee, period):
        if not period:
            return Decimal("0")
        try:
            year, month = [int(part) for part in str(period).split("-")]
            month_start = date(year, month, 1)
            month_end = date(year, month, calendar.monthrange(year, month)[1])
        except (TypeError, ValueError):
            return Decimal("0")

        total = Decimal("0")
        leaves = LeaveRequest.objects.filter(
            employee=employee,
            status="APPROVED",
            leave_type__is_paid=False,
            from_date__lte=month_end,
            to_date__gte=month_start,
        )
        for leave in leaves:
            start = max(leave.from_date, month_start)
            end = min(leave.to_date, month_end)
            total += Decimal((end - start).days + 1)
        return total

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
                    "total_period_days": (
                        calendar.monthrange(
                            int(period.split("-")[0]), int(period.split("-")[1])
                        )[1]
                        if period
                        else 30
                    ),
                    "unpaid_leave_days": self._approved_unpaid_leave_days(item, period),
                    "suggested_payable_days": max(
                        Decimal("0"),
                        Decimal(
                            str(
                                calendar.monthrange(
                                    int(period.split("-")[0]), int(period.split("-")[1])
                                )[1]
                                if period
                                else 30
                            )
                        )
                        - self._approved_unpaid_leave_days(item, period),
                    ),
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
        payable_days_map = request.data.get("payable_days", {}) or {}

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

        year, month = [int(part) for part in str(period).split("-")]
        period_days = Decimal(calendar.monthrange(year, month)[1])

        for employee in employees:
            unpaid_days = self._approved_unpaid_leave_days(employee, period)
            requested_payable = payable_days_map.get(
                str(employee.id), payable_days_map.get(employee.id)
            )
            payable_days = (
                Decimal(str(requested_payable))
                if requested_payable not in (None, "")
                else max(Decimal("0"), period_days - unpaid_days)
            )
            if payable_days < 0 or payable_days > period_days:
                raise serializers.ValidationError(
                    {
                        "payable_days": (
                            f"Payable days for {employee.full_name} must be between "
                            f"0 and {period_days}."
                        )
                    }
                )

            method = "PRORATED" if payable_days < period_days else "FULL"
            factor = payable_days / period_days if period_days else Decimal("0")
            basic = (Decimal(employee.basic_salary or 0) * factor).quantize(
                Decimal("0.01")
            )
            allowances = (Decimal(employee.allowances or 0) * factor).quantize(
                Decimal("0.01")
            )
            gross = basic + allowances
            deductions = Decimal("0")
            net = gross - deductions

            PayrollEntry.objects.create(
                payroll_run=run,
                employee=employee,
                branch=employee.branch,
                period=period,
                basic_salary=basic,
                allowances=allowances,
                gross_salary=gross,
                deductions=deductions,
                net_salary=net,
                total_period_days=period_days,
                payable_days=payable_days,
                unpaid_leave_days=unpaid_days,
                salary_calculation_method=method,
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
    queryset = PayrollEntry.objects.select_related(
        "employee", "branch", "payroll_run"
    ).order_by("-created_at", "-id")
    serializer_class = PayrollEntrySerializer
    search_fields = [
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
        "period",
    ]
    filterset_fields = ["period", "branch", "status", "employee"]

    @staticmethod
    def _month_sequence(from_period, to_period):
        from datetime import date

        try:
            from_year, from_month = [int(part) for part in str(from_period).split("-")]
            to_year, to_month = [int(part) for part in str(to_period).split("-")]

            current = date(from_year, from_month, 1)
            end = date(to_year, to_month, 1)
        except (TypeError, ValueError):
            raise serializers.ValidationError(
                {"period": "From Month and To Month must use YYYY-MM format."}
            )

        if end < current:
            raise serializers.ValidationError(
                {"to_period": "To Month cannot be before From Month."}
            )

        periods = []

        while current <= end:
            periods.append(current.strftime("%Y-%m"))

            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        return periods

    @transaction.atomic
    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-previous",
    )
    def bulk_previous(self, request):
        employee_id = request.data.get("employee")
        from_period = request.data.get("from_period")
        to_period = request.data.get("to_period")
        basic_salary = request.data.get("basic_salary", 0)
        allowances = request.data.get("allowances", 0)
        deductions = request.data.get("deductions", 0)
        payroll_status = request.data.get("status", "PAID")

        if not employee_id:
            return Response(
                {"employee": "Employee is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not from_period:
            return Response(
                {"from_period": "From Month is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not to_period:
            return Response(
                {"to_period": "To Month is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee = Employee.objects.filter(pk=employee_id).first()

        if not employee:
            return Response(
                {"employee": "Employee was not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        periods = self._month_sequence(from_period, to_period)
        current_period = timezone.localdate().strftime("%Y-%m")
        joining_period = (
            employee.joining_date.strftime("%Y-%m") if employee.joining_date else None
        )

        if not joining_period:
            return Response(
                {
                    "employee": (
                        "Employee joining date is required before adding "
                        "previous payroll."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if from_period < joining_period:
            return Response(
                {
                    "from_period": (
                        f"Employee joined in {joining_period}. "
                        "Previous payroll cannot start before the joining month."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if to_period > current_period:
            return Response(
                {"to_period": ("Previous payroll cannot include a future month.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        duplicates = list(
            PayrollEntry.objects.filter(
                employee=employee,
                period__in=periods,
            ).values_list("period", flat=True)
        )

        if duplicates:
            return Response(
                {
                    "period": (
                        "Payroll already exists for: " + ", ".join(sorted(duplicates))
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_entries = []

        for period in periods:
            serializer = self.get_serializer(
                data={
                    "employee": employee.id,
                    "period": period,
                    "basic_salary": basic_salary,
                    "allowances": allowances,
                    "deductions": deductions,
                    "status": payroll_status,
                }
            )
            serializer.is_valid(raise_exception=True)
            created_entries.append(serializer.save())

        return Response(
            {
                "message": (
                    f"{len(created_entries)} previous payroll record(s) created."
                ),
                "count": len(created_entries),
                "periods": periods,
                "results": self.get_serializer(
                    created_entries,
                    many=True,
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


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
