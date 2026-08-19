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

MONEY = Decimal("0.01")


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


from django.contrib.auth import get_user_model


class SalaryAdvanceViewSet(BaseViewSet):
    queryset = SalaryAdvance.objects.select_related(
        "employee",
        "branch",
        "deducted_payroll_entry",
    )
    serializer_class = SalaryAdvanceSerializer
    filterset_fields = [
        "employee",
        "branch",
        "period",
        "status",
        "advance_date",
    ]
    search_fields = [
        "employee__first_name",
        "employee__last_name",
        "employee__employee_code",
        "paid_by",
        "reference_number",
    ]
    ordering_fields = [
        "advance_date",
        "amount",
        "created_at",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch = self.request.query_params.get("branch")
        if branch:
            queryset = queryset.filter(branch_id=branch)

        return queryset

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        branch_id = request.query_params.get("branch")

        employees = Employee.objects.filter(
            is_active=True,
            employment_status__in=[
                "ACTIVE",
                "ON_LEAVE",
                "PROBATION",
            ],
        ).select_related("branch")

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        data = [
            {
                "id": employee.id,
                "employee_code": employee.employee_code,
                "full_name": employee.full_name,
                "branch": employee.branch_id,
                "branch_name": (employee.branch.branch_name if employee.branch else ""),
                "basic_salary": employee.basic_salary,
                "allowances": employee.allowances,
                "total_salary": (
                    getattr(employee, "total_salary", None)
                    or employee.basic_salary
                    or 0
                ),
            }
            for employee in employees.order_by(
                "first_name",
                "last_name",
            )
        ]

        return Response(
            {
                "success": True,
                "message": "Salary advance form options loaded.",
                "data": {"employees": data},
            }
        )


class PayrollRunViewSet(BaseViewSet):
    queryset = (
        PayrollRun.objects.select_related(
            "branch",
            "generated_by",
        )
        .prefetch_related(
            "entries__employee",
            "entries__branch",
        )
        .order_by(
            "-payroll_date",
            "-id",
        )
    )

    serializer_class = PayrollRunSerializer

    filterset_fields = [
        "period",
        "branch",
        "status",
        "payroll_date",
        "paid_by",
    ]

    search_fields = [
        "period",
        "paid_by",
        "entries__employee__first_name",
        "entries__employee__last_name",
        "entries__employee__employee_code",
    ]

    @staticmethod
    def _period_dates(period):
        year, month = [int(part) for part in str(period).split("-")]

        month_start = date(
            year,
            month,
            1,
        )

        month_end = date(
            year,
            month,
            calendar.monthrange(
                year,
                month,
            )[1],
        )

        return (
            month_start,
            month_end,
        )

    @staticmethod
    def _maximum_payroll_period():
        """
        Latest allowed payroll period is next calendar month.

        Previous months, current month, and next month are allowed.
        Anything beyond next month is rejected.
        """
        today_date = timezone.localdate()

        if today_date.month == 12:
            return date(
                today_date.year + 1,
                1,
                1,
            )

        return date(
            today_date.year,
            today_date.month + 1,
            1,
        )

    @classmethod
    def _validated_period_dates(
        cls,
        period,
    ):
        try:
            month_start, month_end = cls._period_dates(period)
        except (
            TypeError,
            ValueError,
            IndexError,
        ):
            raise serializers.ValidationError(
                {"period": ("Period must use YYYY-MM format.")}
            )

        if month_start > cls._maximum_payroll_period():
            raise serializers.ValidationError(
                {
                    "period": (
                        "Future payroll can only be created "
                        "for the next calendar month."
                    )
                }
            )

        return (
            month_start,
            month_end,
        )

    @staticmethod
    def _validate_employee_joining_date(
        employee,
        month_end,
    ):
        if not employee.joining_date:
            raise serializers.ValidationError(
                {
                    "employee_ids": (
                        f"{employee.full_name} does not have "
                        "a joining date. Update the employee "
                        "record before generating payroll."
                    )
                }
            )

        if employee.joining_date > month_end:
            raise serializers.ValidationError(
                {
                    "employee_ids": (
                        f"Payroll cannot be generated for "
                        f"{employee.full_name} before joining "
                        f"date {employee.joining_date}."
                    )
                }
            )

    @staticmethod
    def _approved_unpaid_leave_days(
        employee,
        month_start,
        month_end,
        employment_start,
    ):
        total = Decimal("0")

        leaves = LeaveRequest.objects.filter(
            employee=employee,
            status="APPROVED",
            leave_type__is_paid=False,
            from_date__lte=month_end,
            to_date__gte=employment_start,
        )

        for leave in leaves:
            start = max(
                leave.from_date,
                employment_start,
            )

            end = min(
                leave.to_date,
                month_end,
            )

            if end >= start:
                total += Decimal(str((end - start).days + 1))

        return total

    @staticmethod
    def _employee_loan_deduction(
        employee,
        period,
        available_salary,
    ):
        """
        Calculate loan installment(s) applicable to the payroll period.

        This ONLY calculates the deduction.
        It does NOT reduce EmployeeLoan.remaining_balance.

        The actual loan settlement continues to happen when payroll
        is marked PAID through PayrollEntryViewSet.
        """

        available_salary = max(
            Decimal("0.00"),
            Decimal(str(available_salary or 0)),
        ).quantize(
            MONEY,
            rounding=ROUND_HALF_UP,
        )

        if available_salary <= 0:
            return Decimal("0.00")

        total_deduction = Decimal("0.00")

        loans = EmployeeLoan.objects.filter(
            employee=employee,
            status="ACTIVE",
            start_period__lte=period,
            remaining_balance__gt=0,
        ).order_by(
            "loan_date",
            "id",
        )

        for loan in loans:
            if available_salary <= 0:
                break

            monthly_installment = Decimal(str(loan.monthly_installment or 0)).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            remaining_balance = Decimal(str(loan.remaining_balance or 0)).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            installment = min(
                monthly_installment,
                remaining_balance,
                available_salary,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            if installment <= 0:
                continue

            total_deduction += installment
            available_salary -= installment

        return total_deduction.quantize(
            MONEY,
            rounding=ROUND_HALF_UP,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="eligible-employees",
    )
    def eligible_employees(
        self,
        request,
    ):
        period = str(request.query_params.get("period") or "").strip()

        branch_id = request.query_params.get("branch")

        if not period:
            return Response(
                {"period": ("Pay period is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            month_start, month_end = self._validated_period_dates(period)
        except serializers.ValidationError as exc:
            return Response(
                exc.detail,
                status=status.HTTP_400_BAD_REQUEST,
            )

        employees = (
            Employee.objects.filter(
                is_active=True,
                employment_status__in=[
                    "ACTIVE",
                    "ON_LEAVE",
                    "PROBATION",
                ],
                joining_date__lte=month_end,
            )
            .select_related(
                "branch",
                "department",
            )
            .order_by(
                "first_name",
                "last_name",
                "id",
            )
        )

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        generated_ids = set(
            PayrollEntry.objects.filter(period=period).values_list(
                "employee_id",
                flat=True,
            )
        )

        response = []

        for employee in employees:
            total_period_days = Decimal(str((month_end - month_start).days + 1))

            employment_start = max(
                month_start,
                employee.joining_date or month_start,
            )

            employment_days = Decimal(str((month_end - employment_start).days + 1))

            unpaid_leave_days = self._approved_unpaid_leave_days(
                employee,
                month_start,
                month_end,
                employment_start,
            )

            suggested_payable_days = max(
                Decimal("0"),
                employment_days - unpaid_leave_days,
            )

            pending_advance = SalaryAdvance.objects.filter(
                employee=employee,
                period=period,
                status="PAID",
                remaining_amount__gt=0,
            ).aggregate(total=Sum("remaining_amount"))["total"] or Decimal("0")

            legacy_advance = PayrollEntry.objects.filter(
                employee=employee,
                period=period,
                status="PAID",
            ).exclude(advance_deduction__gt=0).aggregate(total=Sum("advance_amount"))[
                "total"
            ] or Decimal(
                "0"
            )

            basic_salary = Decimal(str(employee.basic_salary or 0))

            allowances = Decimal(str(employee.allowances or 0))

            gross_salary = Decimal(
                str(
                    getattr(
                        employee,
                        "total_salary",
                        None,
                    )
                    or (basic_salary + allowances)
                )
            )

            estimated_gross = (
                gross_salary * suggested_payable_days / total_period_days
                if total_period_days
                else Decimal("0")
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            estimated_advance_deduction = min(
                pending_advance + legacy_advance,
                estimated_gross,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            salary_after_advance = max(
                Decimal("0.00"),
                estimated_gross - estimated_advance_deduction,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            loan_deduction = self._employee_loan_deduction(
                employee=employee,
                period=period,
                available_salary=salary_after_advance,
            )

            estimated_balance = max(
                Decimal("0.00"),
                estimated_gross - estimated_advance_deduction - loan_deduction,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            response.append(
                {
                    "id": employee.id,
                    "employee_code": employee.employee_code,
                    "full_name": employee.full_name,
                    "branch_name": (
                        employee.branch.branch_name if employee.branch else ""
                    ),
                    "joining_date": employee.joining_date,
                    "basic_salary": employee.basic_salary,
                    "allowances": employee.allowances,
                    "gross_salary": gross_salary,
                    "total_period_days": total_period_days,
                    "employment_days": employment_days,
                    "unpaid_leave_days": unpaid_leave_days,
                    "suggested_payable_days": suggested_payable_days,
                    "advance_received": (pending_advance + legacy_advance),
                    "loan_deduction": loan_deduction,
                    "loan_deduction_preview": loan_deduction,
                    "estimated_balance": estimated_balance,
                    "already_generated": (employee.id in generated_ids),
                }
            )

        return Response(
            {
                "success": True,
                "message": ("Eligible payroll employees loaded."),
                "data": response,
            }
        )

    @staticmethod
    def _settle_employee_loan_deduction(
        entry,
    ):
        """
        Apply PayrollEntry.loan_deduction to active loans only when
        the payroll entry is PAID.

        EmployeeLoanRepayment prevents duplicate recovery for the
        same loan/payroll entry combination.
        """
        amount_to_settle = Decimal(str(entry.loan_deduction or 0)).quantize(
            MONEY,
            rounding=ROUND_HALF_UP,
        )

        if amount_to_settle <= 0:
            return

        already_settled = EmployeeLoanRepayment.objects.filter(
            payroll_entry=entry,
        ).aggregate(total=Sum("amount"),)["total"] or Decimal("0.00")

        amount_to_settle = max(
            Decimal("0.00"),
            amount_to_settle - Decimal(str(already_settled or 0)),
        ).quantize(
            MONEY,
            rounding=ROUND_HALF_UP,
        )

        if amount_to_settle <= 0:
            return

        loans = (
            EmployeeLoan.objects.select_for_update()
            .filter(
                employee=entry.employee,
                status="ACTIVE",
                start_period__lte=entry.period,
                remaining_balance__gt=0,
            )
            .order_by(
                "loan_date",
                "id",
            )
        )

        for loan in loans:
            if amount_to_settle <= 0:
                break

            if EmployeeLoanRepayment.objects.filter(
                loan=loan,
                payroll_entry=entry,
            ).exists():
                continue

            current_balance = Decimal(str(loan.remaining_balance or 0)).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            repayment_amount = min(
                current_balance,
                amount_to_settle,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            if repayment_amount <= 0:
                continue

            EmployeeLoanRepayment.objects.create(
                loan=loan,
                payroll_entry=entry,
                employee=entry.employee,
                period=entry.period,
                amount=repayment_amount,
            )

            loan.remaining_balance = max(
                Decimal("0.00"),
                current_balance - repayment_amount,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            if loan.remaining_balance <= 0:
                loan.status = "COMPLETED"

            loan.save(
                update_fields=[
                    "remaining_balance",
                    "status",
                    "updated_at",
                ]
            )

            amount_to_settle = max(
                Decimal("0.00"),
                amount_to_settle - repayment_amount,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

    @action(
        detail=False,
        methods=["post"],
        url_path="generate",
    )
    @transaction.atomic
    def generate(
        self,
        request,
    ):
        period = str(request.data.get("period") or "").strip()

        payroll_date = request.data.get("payroll_date")

        branch_id = request.data.get("branch")

        employee_ids = request.data.get("employee_ids") or []

        payable_days_map = request.data.get("payable_days") or {}

        # IMPORTANT:
        # This is the status selected in the frontend.
        requested_status = str(request.data.get("status") or "PENDING").strip().upper()

        # Paid By remains a TEXT value.
        paid_by = str(request.data.get("paid_by") or "").strip()

        valid_statuses = {value for value, _label in PayrollEntry.STATUS_CHOICES}

        if requested_status not in valid_statuses:
            return Response(
                {"status": ("Select a valid payroll status.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not period:
            return Response(
                {"period": ("Pay period is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not payroll_date:
            return Response(
                {"payroll_date": ("Payroll date is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if requested_status == "PAID" and not paid_by:
            return Response(
                {"paid_by": ("Paid By is required when " "status is Paid.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not employee_ids:
            return Response(
                {"employee_ids": ("Select at least one employee.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            month_start, month_end = self._validated_period_dates(period)
        except serializers.ValidationError as exc:
            return Response(
                exc.detail,
                status=status.HTTP_400_BAD_REQUEST,
            )

        employees = (
            Employee.objects.filter(
                id__in=employee_ids,
                is_active=True,
                joining_date__lte=month_end,
            )
            .select_related("branch")
            .order_by("id")
        )

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        requested_employee_ids = {int(employee_id) for employee_id in employee_ids}

        selected_employee_ids = set(
            employees.values_list(
                "id",
                flat=True,
            )
        )

        missing_employee_ids = requested_employee_ids - selected_employee_ids

        if missing_employee_ids:
            return Response(
                {
                    "employee_ids": (
                        "One or more selected employees are "
                        "not eligible for the selected payroll "
                        "period or branch."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not employees.exists():
            return Response(
                {"employee_ids": ("No eligible employees were found.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        run_status_map = {
            "PENDING": "DRAFT",
            "PROCESSING": "PROCESSING",
            "PAID": "COMPLETED",
            "FAILED": "FAILED",
            "CANCELLED": "CANCELLED",
        }

        run = PayrollRun.objects.create(
            period=period,
            payroll_date=payroll_date,
            branch_id=(branch_id or None),
            paid_by=(paid_by if requested_status == "PAID" else ""),
            status=run_status_map[requested_status],
            generated_by=request.user,
            generated_at=timezone.now(),
        )

        created_entries = []

        # Keep the existing advance deduction behavior.
        advance_rows_to_update = []

        for employee in employees:
            try:
                self._validate_employee_joining_date(
                    employee,
                    month_end,
                )
            except serializers.ValidationError as exc:
                return Response(
                    exc.detail,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if PayrollEntry.objects.filter(
                employee=employee,
                period=period,
            ).exists():
                continue

            total_period_days = Decimal(str((month_end - month_start).days + 1))

            employment_start = max(
                month_start,
                employee.joining_date or month_start,
            )

            employment_days = Decimal(str((month_end - employment_start).days + 1))

            unpaid_leave_days = self._approved_unpaid_leave_days(
                employee,
                month_start,
                month_end,
                employment_start,
            )

            default_payable_days = max(
                Decimal("0"),
                employment_days - unpaid_leave_days,
            )

            requested_days = payable_days_map.get(
                str(employee.id),
                payable_days_map.get(
                    employee.id,
                    default_payable_days,
                ),
            )

            try:
                payable_days = Decimal(
                    str(
                        requested_days
                        if requested_days
                        not in (
                            None,
                            "",
                        )
                        else default_payable_days
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                return Response(
                    {
                        "payable_days": (
                            f"Invalid payable days for " f"{employee.full_name}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if payable_days < 0 or payable_days > employment_days:
                return Response(
                    {
                        "payable_days": (
                            f"Payable days for "
                            f"{employee.full_name} "
                            f"must be between 0 and "
                            f"{employment_days}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            basic_salary = Decimal(str(employee.basic_salary or 0))

            allowances = Decimal(str(employee.allowances or 0))

            monthly_gross = Decimal(
                str(
                    getattr(
                        employee,
                        "total_salary",
                        None,
                    )
                    or (basic_salary + allowances)
                )
            )

            gross_salary = (
                monthly_gross * payable_days / total_period_days
                if total_period_days
                else Decimal("0")
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            regular_deductions = Decimal("0")

            advance_rows = list(
                SalaryAdvance.objects.select_for_update()
                .filter(
                    employee=employee,
                    period=period,
                    status="PAID",
                    remaining_amount__gt=0,
                )
                .order_by(
                    "advance_date",
                    "id",
                )
            )

            available_advance = sum(
                (Decimal(advance.remaining_amount or 0) for advance in advance_rows),
                Decimal("0"),
            )

            advance_deduction = min(
                available_advance,
                max(
                    Decimal("0"),
                    gross_salary - regular_deductions,
                ),
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            available_for_loan = max(
                Decimal("0.00"),
                gross_salary - regular_deductions - advance_deduction,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            loan_deduction = self._employee_loan_deduction(
                employee=employee,
                period=period,
                available_salary=available_for_loan,
            )

            net_salary = max(
                Decimal("0.00"),
                gross_salary - regular_deductions - advance_deduction - loan_deduction,
            ).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )

            # FIX:
            # Do NOT hard-code status="PENDING".
            # Save exactly the status selected in the UI.
            entry = PayrollEntry.objects.create(
                payroll_run=run,
                employee=employee,
                branch=employee.branch,
                period=period,
                payroll_date=payroll_date,
                paid_by=(paid_by if requested_status == "PAID" else ""),
                basic_salary=basic_salary,
                allowances=allowances,
                gross_salary=gross_salary,
                deductions=(regular_deductions),
                advance_deduction=(advance_deduction),
                loan_deduction=(loan_deduction),
                net_salary=net_salary,
                balance_payable=net_salary,
                status=requested_status,
                paid_at=(timezone.now() if requested_status == "PAID" else None),
                total_period_days=(total_period_days),
                payable_days=(payable_days),
                unpaid_leave_days=(unpaid_leave_days),
                salary_calculation_method=(
                    "PRORATED" if payable_days < total_period_days else "FULL"
                ),
            )

            created_entries.append(entry)

            if requested_status == "PAID":
                self._settle_employee_loan_deduction(entry)

            remaining_to_apply = advance_deduction

            for advance in advance_rows:
                if remaining_to_apply <= 0:
                    break

                applied = min(
                    Decimal(advance.remaining_amount or 0),
                    remaining_to_apply,
                )

                advance.remaining_amount = (
                    Decimal(advance.remaining_amount or 0) - applied
                ).quantize(
                    MONEY,
                    rounding=ROUND_HALF_UP,
                )

                remaining_to_apply -= applied

                if advance.remaining_amount <= 0:
                    advance.status = "DEDUCTED"

                    advance.deducted_payroll_entry = entry

                advance_rows_to_update.append(advance)

        if not created_entries:
            run.delete()

            return Response(
                {
                    "employee_ids": (
                        "Payroll already exists "
                        "for the selected employees "
                        "and period."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if advance_rows_to_update:
            # Remove duplicate model objects before bulk update.
            deduped_advances = {item.pk: item for item in advance_rows_to_update}

            SalaryAdvance.objects.bulk_update(
                list(deduped_advances.values()),
                [
                    "remaining_amount",
                    "status",
                    "deducted_payroll_entry",
                    "updated_at",
                ],
            )

        run.total_gross = sum(
            (Decimal(entry.gross_salary or 0) for entry in created_entries),
            Decimal("0"),
        )

        run.total_deductions = sum(
            (Decimal(entry.deductions or 0) for entry in created_entries),
            Decimal("0"),
        )

        run.total_advance_deduction = sum(
            (Decimal(entry.advance_deduction or 0) for entry in created_entries),
            Decimal("0"),
        )

        run.total_net = sum(
            (Decimal(entry.net_salary or 0) for entry in created_entries),
            Decimal("0"),
        )

        # FIX:
        # Do NOT force run.status = "COMPLETED".
        run.status = run_status_map[requested_status]

        run.paid_by = paid_by if requested_status == "PAID" else ""

        run.save(
            update_fields=[
                "total_gross",
                "total_deductions",
                "total_advance_deduction",
                "total_net",
                "status",
                "paid_by",
                "updated_at",
            ]
        )

        return Response(
            {
                "success": True,
                "message": ("Payroll generated " f"with {requested_status} status."),
                "data": PayrollRunSerializer(run).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="summary",
    )
    def summary(
        self,
        request,
    ):
        queryset = PayrollEntry.objects.all()

        period = request.query_params.get("period")

        branch = request.query_params.get("branch")

        status_value = request.query_params.get("status")

        if period:
            queryset = queryset.filter(period=period)

        if branch:
            queryset = queryset.filter(branch_id=branch)

        if status_value:
            queryset = queryset.filter(status=status_value)

        totals = queryset.aggregate(
            gross=Sum("gross_salary"),
            deductions=Sum("deductions"),
            advance_deductions=Sum("advance_deduction"),
            loan_deductions=Sum("loan_deduction"),
            net=Sum("net_salary"),
        )

        advance_qs = SalaryAdvance.objects.all()

        if period:
            advance_qs = advance_qs.filter(period=period)

        if branch:
            advance_qs = advance_qs.filter(branch_id=branch)

        total_advances = advance_qs.filter(
            status__in=[
                "PAID",
                "DEDUCTED",
            ],
        ).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")

        return Response(
            {
                "success": True,
                "message": ("Payroll summary loaded."),
                "data": {
                    "employees_on_payroll": (
                        queryset.values("employee_id").distinct().count()
                    ),
                    "total_gross": (totals["gross"] or 0),
                    "total_deductions": (totals["deductions"] or 0),
                    "total_advances": (total_advances),
                    "total_advance_deductions": (totals["advance_deductions"] or 0),
                    "total_loan_deductions": (totals["loan_deductions"] or 0),
                    "total_net": (totals["net"] or 0),
                },
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="export",
    )
    def export(
        self,
        request,
    ):
        queryset = PayrollEntry.objects.select_related(
            "employee",
            "branch",
        ).order_by(
            "period",
            "employee__employee_code",
        )

        period = request.query_params.get("period")

        branch = request.query_params.get("branch")

        if period:
            queryset = queryset.filter(period=period)

        if branch:
            queryset = queryset.filter(branch_id=branch)

        response = HttpResponse(content_type="text/csv")

        response["Content-Disposition"] = (
            f"attachment; " f'filename="payroll-' f'{period or "all"}.csv"'
        )

        writer = csv.writer(response)

        writer.writerow(
            [
                "Employee Code",
                "Employee",
                "Period",
                "Payroll Date",
                "Payable Days",
                "Total Period Days",
                "Basic Salary",
                "Allowances",
                "Gross Salary",
                "Deductions",
                "Advance Deduction",
                "Loan Deduction",
                "Net Salary",
                "Paid By",
                "Method",
                "Status",
            ]
        )

        for entry in queryset:
            writer.writerow(
                [
                    entry.employee.employee_code,
                    entry.employee.full_name,
                    entry.period,
                    entry.payroll_date,
                    entry.payable_days,
                    entry.total_period_days,
                    entry.basic_salary,
                    entry.allowances,
                    entry.gross_salary,
                    entry.deductions,
                    entry.advance_deduction,
                    entry.loan_deduction,
                    entry.net_salary,
                    entry.paid_by,
                    entry.salary_calculation_method,
                    entry.status,
                ]
            )

        return response


class EmployeeLoanViewSet(BaseViewSet):
    queryset = EmployeeLoan.objects.select_related(
        "employee",
        "branch",
        "created_by",
    ).prefetch_related(
        "repayments",
    )

    serializer_class = EmployeeLoanSerializer

    filterset_fields = [
        "employee",
        "branch",
        "status",
        "start_period",
        "loan_date",
    ]

    search_fields = [
        "employee__first_name",
        "employee__last_name",
        "employee__employee_code",
        "reference_number",
        "reason",
    ]

    ordering_fields = [
        "loan_date",
        "amount",
        "monthly_installment",
        "remaining_balance",
        "created_at",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch")

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        return queryset

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        branch_id = request.query_params.get("branch")

        employees = Employee.objects.filter(
            is_active=True,
            employment_status__in=[
                "ACTIVE",
                "ON_LEAVE",
                "PROBATION",
            ],
        ).select_related("branch")

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        employee_rows = []

        for employee in employees.order_by(
            "first_name",
            "last_name",
        ):
            employee_rows.append(
                {
                    "id": employee.id,
                    "employee_code": employee.employee_code,
                    "full_name": employee.full_name,
                    "branch": employee.branch_id,
                    "branch_name": (
                        employee.branch.branch_name if employee.branch else ""
                    ),
                    "basic_salary": employee.basic_salary,
                    "allowances": employee.allowances,
                }
            )

        return Response(
            {
                "success": True,
                "message": ("Employee loan form options loaded."),
                "data": {
                    "employees": employee_rows,
                },
            }
        )

    @transaction.atomic
    @action(
        detail=True,
        methods=["post"],
    )
    def cancel(self, request, pk=None):
        loan = self.get_object()

        if loan.status == "COMPLETED":
            return Response(
                {
                    "success": False,
                    "message": ("A completed loan cannot be cancelled."),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if loan.status == "CANCELLED":
            return Response(
                {
                    "success": False,
                    "message": ("This loan is already cancelled."),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        loan.status = "CANCELLED"

        loan.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        return Response(
            {
                "success": True,
                "message": ("Employee loan cancelled successfully."),
                "data": self.get_serializer(loan).data,
            }
        )


class PayrollEntryViewSet(BaseViewSet):
    queryset = PayrollEntry.objects.select_related(
        "employee",
        "branch",
        "payroll_run",
    ).order_by(
        "-payroll_date",
        "-id",
    )

    serializer_class = PayrollEntrySerializer

    filterset_fields = [
        "employee",
        "branch",
        "period",
        "status",
        "payroll_date",
        "paid_by",
    ]

    search_fields = [
        "employee__first_name",
        "employee__last_name",
        "employee__employee_code",
        "paid_by",
        "period",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch = self.request.query_params.get("branch")

        if branch:
            queryset = queryset.filter(branch_id=branch)

        return queryset

    def _calculate_employee_loan_deduction(self, entry):
        """
        Calculate the loan installment that should be deducted from this
        payroll entry.

        This does not change any EmployeeLoan balance. It only calculates
        the deduction from ACTIVE loans that are eligible for this period.
        """
        gross_salary = Decimal(str(entry.gross_salary or 0)).quantize(MONEY)

        regular_deductions = Decimal(str(entry.deductions or 0)).quantize(MONEY)

        advance_deduction = Decimal(str(entry.advance_deduction or 0)).quantize(MONEY)

        available_salary = max(
            Decimal("0.00"),
            gross_salary - regular_deductions - advance_deduction,
        ).quantize(MONEY)

        if available_salary <= 0:
            return Decimal("0.00")

        total_deduction = Decimal("0.00")

        loans = (
            EmployeeLoan.objects.select_for_update()
            .filter(
                employee=entry.employee,
                status="ACTIVE",
                start_period__lte=entry.period,
                remaining_balance__gt=0,
            )
            .order_by(
                "loan_date",
                "id",
            )
        )

        for loan in loans:
            if available_salary <= 0:
                break

            monthly_installment = Decimal(str(loan.monthly_installment or 0)).quantize(
                MONEY
            )

            remaining_balance = Decimal(str(loan.remaining_balance or 0)).quantize(
                MONEY
            )

            installment = min(
                monthly_installment,
                remaining_balance,
                available_salary,
            ).quantize(MONEY)

            if installment <= 0:
                continue

            total_deduction += installment
            available_salary -= installment

        return total_deduction.quantize(MONEY)

    def _ensure_employee_loan_deduction(self, entry):
        """
        Make sure PayrollEntry.loan_deduction and net salary reflect the
        employee's active loan before salary is marked PAID.

        This is mainly a safety net for payroll entries that were generated
        before loan-deduction support was added.
        """
        calculated_loan_deduction = self._calculate_employee_loan_deduction(entry)

        current_loan_deduction = Decimal(str(entry.loan_deduction or 0)).quantize(MONEY)

        if current_loan_deduction == calculated_loan_deduction:
            return

        entry.loan_deduction = calculated_loan_deduction

        gross_salary = Decimal(str(entry.gross_salary or 0)).quantize(MONEY)

        regular_deductions = Decimal(str(entry.deductions or 0)).quantize(MONEY)

        advance_deduction = Decimal(str(entry.advance_deduction or 0)).quantize(MONEY)

        entry.net_salary = max(
            Decimal("0.00"),
            gross_salary
            - regular_deductions
            - advance_deduction
            - calculated_loan_deduction,
        ).quantize(MONEY)

        if str(entry.status or "").upper() != "PAID":
            entry.balance_payable = entry.net_salary

        entry.save(
            update_fields=[
                "loan_deduction",
                "net_salary",
                "balance_payable",
                "updated_at",
            ]
        )

    def _settle_employee_loans(self, entry):
        """
        Apply the loan deduction stored on this payroll entry to the
        employee's active loans.

        This method is idempotent:
        EmployeeLoanRepayment has a unique constraint for
        (loan, payroll_entry), so calling this method again will not
        deduct the same repayment twice.
        """
        planned_deduction = Decimal(entry.loan_deduction or 0).quantize(MONEY)

        if planned_deduction <= 0:
            return

        already_settled = EmployeeLoanRepayment.objects.filter(
            payroll_entry=entry
        ).aggregate(total=Sum("amount")).get("total") or Decimal("0.00")

        amount_to_settle = max(
            Decimal("0.00"),
            planned_deduction - Decimal(already_settled),
        ).quantize(MONEY)

        if amount_to_settle <= 0:
            return

        loans = (
            EmployeeLoan.objects.select_for_update()
            .filter(
                employee=entry.employee,
                status="ACTIVE",
                start_period__lte=entry.period,
                remaining_balance__gt=0,
            )
            .order_by(
                "loan_date",
                "id",
            )
        )

        for loan in loans:
            if amount_to_settle <= 0:
                break

            existing_repayment = EmployeeLoanRepayment.objects.filter(
                loan=loan,
                payroll_entry=entry,
            ).exists()

            if existing_repayment:
                continue

            loan_balance = Decimal(loan.remaining_balance or 0).quantize(MONEY)

            if loan_balance <= 0:
                loan.status = "COMPLETED"
                loan.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )
                continue

            repayment_amount = min(
                amount_to_settle,
                loan_balance,
            ).quantize(MONEY)

            if repayment_amount <= 0:
                continue

            EmployeeLoanRepayment.objects.create(
                loan=loan,
                payroll_entry=entry,
                employee=entry.employee,
                period=entry.period,
                amount=repayment_amount,
            )

            loan.remaining_balance = max(
                Decimal("0.00"),
                loan_balance - repayment_amount,
            ).quantize(MONEY)

            if loan.remaining_balance <= 0:
                loan.status = "COMPLETED"

            loan.save(
                update_fields=[
                    "remaining_balance",
                    "status",
                    "updated_at",
                ]
            )

            amount_to_settle = max(
                Decimal("0.00"),
                amount_to_settle - repayment_amount,
            ).quantize(MONEY)

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(
        self,
        request,
    ):
        paid_by_values = (
            PayrollEntry.objects.exclude(paid_by__isnull=True)
            .exclude(paid_by="")
            .values_list(
                "paid_by",
                flat=True,
            )
            .distinct()
            .order_by("paid_by")
        )

        return Response(
            {
                "success": True,
                "message": ("Payroll form options loaded."),
                "data": {
                    "statuses": [
                        {
                            "value": "PENDING",
                            "label": "Pending",
                        },
                        {
                            "value": "PROCESSING",
                            "label": "Processing",
                        },
                        {
                            "value": "PAID",
                            "label": "Paid",
                        },
                        {
                            "value": "FAILED",
                            "label": "Failed",
                        },
                        {
                            "value": "CANCELLED",
                            "label": "Cancelled",
                        },
                    ],
                    "paid_by_options": [
                        {
                            "value": value,
                            "label": value,
                        }
                        for value in paid_by_values
                    ],
                },
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="update-status",
    )
    @transaction.atomic
    def update_status(
        self,
        request,
        pk=None,
    ):
        entry_id = self.get_object().pk

        entry = PayrollEntry.objects.select_for_update().get(pk=entry_id)

        requested_status = str(request.data.get("status") or "").strip().upper()

        valid_statuses = {value for value, _label in PayrollEntry.STATUS_CHOICES}

        if requested_status not in valid_statuses:
            return Response(
                {"status": ("Select a valid payroll status.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_status = str(entry.status or "PENDING").upper()

        transitions = {
            "PENDING": {
                "PROCESSING",
                "PAID",
                "FAILED",
                "CANCELLED",
            },
            "PROCESSING": {
                "PAID",
                "FAILED",
                "CANCELLED",
            },
            "FAILED": {
                "PENDING",
                "PROCESSING",
                "PAID",
                "CANCELLED",
            },
            "PAID": set(),
            "CANCELLED": set(),
        }

        if requested_status == current_status:
            return Response(
                {
                    "success": True,
                    "message": ("Payroll status is unchanged."),
                    "data": (self.get_serializer(entry).data),
                }
            )

        if requested_status not in transitions.get(
            current_status,
            set(),
        ):
            return Response(
                {
                    "status": (
                        f"Status cannot change "
                        f"from {current_status} "
                        f"to {requested_status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_by = str(request.data.get("paid_by") or "").strip()

        entry.status = requested_status

        update_fields = [
            "status",
            "updated_at",
        ]

        if requested_status == "PAID":
            if not paid_by:
                return Response(
                    {
                        "paid_by": (
                            "Paid By is required " "when marking payroll " "as Paid."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            self._ensure_employee_loan_deduction(entry)

            entry.paid_by = paid_by
            entry.paid_at = timezone.now()

            update_fields.extend(
                [
                    "paid_by",
                    "paid_at",
                ]
            )

        else:
            entry.paid_by = ""
            entry.paid_at = None

            update_fields.extend(
                [
                    "paid_by",
                    "paid_at",
                ]
            )

        entry.save(update_fields=update_fields)

        if requested_status == "PAID" and current_status != "PAID":
            self._settle_employee_loans(entry)

        payroll_run = entry.payroll_run

        if payroll_run:
            entries = payroll_run.entries.all()

            total_entries = entries.count()

            if (
                total_entries > 0
                and entries.filter(status="PAID").count() == total_entries
            ):
                payroll_run.status = "COMPLETED"

            elif entries.filter(status="PROCESSING").exists():
                payroll_run.status = "PROCESSING"

            elif entries.filter(status="FAILED").exists():
                payroll_run.status = "FAILED"

            elif (
                total_entries > 0
                and entries.filter(status="CANCELLED").count() == total_entries
            ):
                payroll_run.status = "CANCELLED"

            else:
                payroll_run.status = "DRAFT"

            if hasattr(
                payroll_run,
                "paid_by",
            ):
                if payroll_run.status == "COMPLETED":
                    paid_entry = (
                        entries.filter(status="PAID").exclude(paid_by="").first()
                    )

                    payroll_run.paid_by = paid_entry.paid_by if paid_entry else ""
                else:
                    payroll_run.paid_by = ""

            run_update_fields = [
                "status",
                "updated_at",
            ]

            if hasattr(
                payroll_run,
                "paid_by",
            ):
                run_update_fields.append("paid_by")

            payroll_run.save(update_fields=(run_update_fields))

        return Response(
            {
                "success": True,
                "message": ("Payroll status updated successfully."),
                "data": (self.get_serializer(entry).data),
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="mark-paid",
    )
    @transaction.atomic
    def mark_paid(
        self,
        request,
        pk=None,
    ):
        entry_id = self.get_object().pk

        entry = PayrollEntry.objects.select_for_update().get(pk=entry_id)

        current_status = str(entry.status or "").upper()

        if current_status == "PAID":
            return Response(
                {
                    "success": True,
                    "message": ("Payroll is already marked as paid."),
                    "data": (self.get_serializer(entry).data),
                }
            )

        if current_status == "CANCELLED":
            return Response(
                {"status": ("Cancelled payroll cannot " "be marked as paid.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_by = str(request.data.get("paid_by") or entry.paid_by or "").strip()

        if not paid_by:
            return Response(
                {"paid_by": ("Paid By is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self._ensure_employee_loan_deduction(entry)

        entry.paid_by = paid_by
        entry.status = "PAID"
        entry.paid_at = timezone.now()

        entry.save(
            update_fields=[
                "paid_by",
                "status",
                "paid_at",
                "updated_at",
            ]
        )

        self._settle_employee_loans(entry)

        payroll_run = entry.payroll_run

        if payroll_run:
            entries = payroll_run.entries.all()

            total_entries = entries.count()

            paid_count = entries.filter(status="PAID").count()

            if total_entries > 0 and paid_count == total_entries:
                payroll_run.status = "COMPLETED"

                if hasattr(
                    payroll_run,
                    "paid_by",
                ):
                    payroll_run.paid_by = paid_by

                fields = [
                    "status",
                    "updated_at",
                ]

                if hasattr(
                    payroll_run,
                    "paid_by",
                ):
                    fields.append("paid_by")

                payroll_run.save(update_fields=fields)

        return Response(
            {
                "success": True,
                "message": ("Payroll marked as paid."),
                "data": (self.get_serializer(entry).data),
            }
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
        branch_id = request.query_params.get("branch")

        employees = Employee.objects.filter(is_active=True)
        attendance = Attendance.objects.filter(
            date=today,
            status="PRESENT",
        )
        leaves = LeaveRequest.objects.filter(status="PENDING")
        payroll = PayrollEntry.objects.filter(period=today.strftime("%Y-%m"))

        if branch_id:
            employees = employees.filter(branch_id=branch_id)
            attendance = attendance.filter(branch_id=branch_id)
            leaves = leaves.filter(branch_id=branch_id)
            payroll = payroll.filter(branch_id=branch_id)

        return Response(
            {
                "employees": employees.count(),
                "present_today": attendance.count(),
                "pending_leaves": leaves.count(),
                "payroll_net": (
                    payroll.aggregate(value=Sum("net_salary"))["value"] or 0
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
            if start_date:
                queryset = queryset.filter(to_date__gte=start_date)
            if end_date:
                queryset = queryset.filter(from_date__lte=end_date)
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
            if start_date:
                queryset = queryset.filter(payroll_date__gte=start_date)
            if end_date:
                queryset = queryset.filter(payroll_date__lte=end_date)
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
        if start_date:
            queryset = queryset.filter(joining_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(joining_date__lte=end_date)

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


class SalaryCertificateViewSet(BaseViewSet):
    queryset = SalaryCertificate.objects.select_related(
        "employee",
        "employee__branch",
        "employee__designation",
        "issued_by",
    ).order_by(
        "-certificate_date",
        "-id",
    )

    serializer_class = SalaryCertificateSerializer

    search_fields = [
        "reference_number",
        "employee_name",
        "employee_code",
        "identity_number",
        "designation_name",
        "authorized_signatory",
    ]

    filterset_fields = [
        "employee",
        "certificate_date",
    ]

    ordering_fields = [
        "reference_number",
        "certificate_date",
        "employee_name",
        "created_at",
    ]

    # Certificates are immutable after issue.
    # A correction should be issued as a new certificate.
    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch")

        if branch_id and str(branch_id).lower() != "all":
            queryset = queryset.filter(employee__branch_id=branch_id)

        return queryset


# Add this method INSIDE your existing EmployeeViewSet class.


@action(
    detail=True,
    methods=["get"],
    url_path="salary-certificate-data",
)
def salary_certificate_data(
    self,
    request,
    pk=None,
):
    employee = self.get_object()

    if employee.employment_status not in [
        "ACTIVE",
        "PROBATION",
        "ON_LEAVE",
    ]:
        return Response(
            {
                "detail": (
                    "Salary certificates can only be "
                    "issued for currently employed employees."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    basic_salary = Decimal(employee.basic_salary or 0)

    allowances = Decimal(employee.allowances or 0)

    # The current Employee model stores all allowances
    # in one field. For the certificate we initially map
    # that value to Transport / Other Allowance.
    #
    # HR can manually split the amount into Housing and
    # Transport / Other before issuing the certificate.
    housing_allowance = Decimal("0")

    transport_other_allowance = allowances

    return Response(
        {
            "employee": (employee.id),
            "employee_name": (employee.full_name),
            "employee_code": (employee.employee_code or ""),
            "branch": (employee.branch_id),
            "branch_name": (employee.branch.branch_name if employee.branch else ""),
            "designation": (employee.designation_id),
            "designation_name": (
                employee.designation.name if employee.designation else ""
            ),
            "joining_date": (employee.joining_date),
            "passport_number": (employee.passport_number or ""),
            "emirates_id_number": (employee.emirates_id_number or ""),
            "identity_number": (
                employee.passport_number or employee.emirates_id_number or ""
            ),
            "basic_salary": (basic_salary),
            "allowances": (allowances),
            "housing_allowance": (housing_allowance),
            "transport_other_allowance": (transport_other_allowance),
            "total_monthly_salary": (
                basic_salary + housing_allowance + transport_other_allowance
            ),
        }
    )


class EmployeeLetterViewSet(BaseViewSet):
    queryset = EmployeeLetter.objects.select_related(
        "employee",
        "employee__branch",
        "employee__designation",
        "employee__department",
        "issued_by",
    ).order_by("-letter_date", "-id")

    serializer_class = EmployeeLetterSerializer

    search_fields = [
        "reference_number",
        "employee_name",
        "employee_code",
        "designation_name",
        "department_name",
        "subject",
        "reason",
    ]

    filterset_fields = [
        "employee",
        "letter_type",
        "letter_date",
    ]

    ordering_fields = [
        "reference_number",
        "letter_date",
        "employee_name",
        "created_at",
    ]

    # Issued HR letters are immutable. Corrections should be re-issued.
    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch")

        if branch_id and str(branch_id).lower() != "all":
            queryset = queryset.filter(employee__branch_id=branch_id)

        return queryset
