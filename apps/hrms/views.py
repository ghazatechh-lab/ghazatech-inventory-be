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


from django.contrib.auth import get_user_model


class PayrollRunViewSet(BaseViewSet):
    queryset = PayrollRun.objects.select_related(
        "branch",
        "generated_by",
        "paid_by",
    ).prefetch_related(
        "entries__employee",
        "entries__branch",
        "entries__paid_by",
    )
    serializer_class = PayrollRunSerializer
    filterset_fields = [
        "period",
        "branch",
        "status",
        "salary_type",
        "payroll_date",
        "paid_by",
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
    def _approved_unpaid_leave_days(
        employee,
        period,
    ):
        if not period:
            return Decimal("0")

        try:
            month_start, month_end = PayrollRunViewSet._period_dates(period)
        except (
            TypeError,
            ValueError,
        ):
            return Decimal("0")

        employment_start = max(
            month_start,
            employee.joining_date or month_start,
        )
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
                total += Decimal((end - start).days + 1)

        return total

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        User = get_user_model()

        user_fields = {field.name for field in User._meta.get_fields()}

        paid_by_users = User.objects.all()

        if "is_active" in user_fields:
            active_users = paid_by_users.filter(is_active=True)

            # Keep a safe fallback for older imported user data.
            if active_users.exists():
                paid_by_users = active_users

        ordering = []

        if "first_name" in user_fields:
            ordering.append("first_name")

        if "username" in user_fields:
            ordering.append("username")

        if ordering:
            paid_by_users = paid_by_users.order_by(*ordering)

        options = []

        for user in paid_by_users:
            name = ""

            if hasattr(
                user,
                "get_full_name",
            ):
                name = (user.get_full_name() or "").strip()

            name = (
                name
                or getattr(
                    user,
                    "username",
                    "",
                )
                or getattr(
                    user,
                    "email",
                    "",
                )
                or f"User #{user.pk}"
            )

            options.append(
                {
                    "id": user.pk,
                    "name": name,
                    "email": getattr(
                        user,
                        "email",
                        "",
                    ),
                    "is_current_user": (
                        request.user.is_authenticated and user.pk == request.user.pk
                    ),
                }
            )

        return Response(
            {
                "success": True,
                "message": ("Payroll form options loaded."),
                "data": {
                    "paid_by_users": options,
                },
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="eligible-employees",
    )
    def eligible_employees(self, request):
        period = request.query_params.get("period")
        branch_id = request.query_params.get("branch")
        salary_type = str(
            request.query_params.get(
                "salary_type",
                "REGULAR",
            )
            or "REGULAR"
        ).upper()

        if not period:
            return Response(
                {"period": ("Pay period is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            month_start, month_end = self._period_dates(period)
        except (
            TypeError,
            ValueError,
        ):
            return Response(
                {"period": ("Period must use YYYY-MM " "format.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employees = Employee.objects.filter(
            is_active=True,
            employment_status__in=[
                "ACTIVE",
                "ON_LEAVE",
                "PROBATION",
            ],
            joining_date__lte=month_end,
        ).select_related(
            "branch",
            "department",
        )

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        used_regular_ids = set(
            PayrollEntry.objects.filter(
                period=period,
                salary_type="REGULAR",
            ).values_list(
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
                period,
            )
            suggested_payable_days = max(
                Decimal("0.00"),
                employment_days - unpaid_leave_days,
            )

            paid_advance = PayrollEntry.objects.filter(
                employee=employee,
                period=period,
                salary_type="ADVANCE",
                status="PAID",
            ).aggregate(total=Sum("advance_amount"))["total"] or Decimal("0.00")

            response.append(
                {
                    "id": employee.id,
                    "employee_code": (employee.employee_code),
                    "full_name": (employee.full_name),
                    "branch_name": (
                        employee.branch.branch_name if employee.branch else ""
                    ),
                    "joining_date": (employee.joining_date),
                    "basic_salary": (employee.basic_salary),
                    "allowances": (employee.allowances),
                    "gross_salary": (employee.total_salary),
                    "total_period_days": (total_period_days),
                    "employment_days": (employment_days),
                    "unpaid_leave_days": (unpaid_leave_days),
                    "suggested_payable_days": (suggested_payable_days),
                    "advance_received": (paid_advance),
                    "already_generated": (
                        salary_type == "REGULAR" and employee.id in used_regular_ids
                    ),
                }
            )

        return Response(response)

    @transaction.atomic
    @action(
        detail=False,
        methods=["post"],
    )
    def generate(self, request):
        period = request.data.get("period")
        payroll_date = request.data.get("payroll_date")
        salary_type = str(
            request.data.get(
                "salary_type",
                "REGULAR",
            )
            or "REGULAR"
        ).upper()
        branch_id = request.data.get("branch")
        paid_by_id = request.data.get("paid_by")
        employee_ids = request.data.get(
            "employee_ids",
            [],
        )
        payable_days_map = (
            request.data.get(
                "payable_days",
                {},
            )
            or {}
        )
        advance_amounts = (
            request.data.get(
                "advance_amounts",
                {},
            )
            or {}
        )

        errors = {}

        if not period:
            errors["period"] = "Pay period is required."

        if not payroll_date:
            errors["payroll_date"] = "Payroll Date is required."

        if not paid_by_id:
            errors["paid_by"] = "Paid By is required."

        if salary_type not in {
            "REGULAR",
            "ADVANCE",
        }:
            errors["salary_type"] = "Select Regular Salary or " "Advance Salary."

        if not employee_ids:
            errors["employee_ids"] = "Select at least one employee."

        if errors:
            return Response(
                errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        employees = Employee.objects.filter(
            id__in=employee_ids,
            is_active=True,
        ).select_related(
            "branch",
        )

        if branch_id:
            employees = employees.filter(branch_id=branch_id)

        if salary_type == "REGULAR":
            employees = employees.exclude(
                id__in=(
                    PayrollEntry.objects.filter(
                        period=period,
                        salary_type="REGULAR",
                    ).values_list(
                        "employee_id",
                        flat=True,
                    )
                )
            )

        if not employees.exists():
            return Response(
                {"detail": ("No eligible employees " "were selected.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_by = (
            get_user_model()
            .objects.filter(
                pk=paid_by_id,
                is_active=True,
            )
            .first()
        )

        if not paid_by:
            return Response(
                {"paid_by": ("Selected payer was not " "found.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        run = PayrollRun.objects.create(
            period=period,
            payroll_date=payroll_date,
            salary_type=salary_type,
            branch_id=(branch_id or None),
            paid_by=paid_by,
            status="PROCESSING",
            generated_by=request.user,
            generated_at=timezone.now(),
        )

        created_entries = []

        for employee in employees:
            payload = {
                "employee": employee.id,
                "period": period,
                "payroll_date": payroll_date,
                "salary_type": salary_type,
                "paid_by": paid_by.id,
                "status": "PAID",
            }

            if salary_type == "ADVANCE":
                payload["advance_amount"] = advance_amounts.get(
                    str(employee.id),
                    advance_amounts.get(
                        employee.id,
                    ),
                )
            else:
                payload.update(
                    {
                        "basic_salary": (employee.basic_salary or 0),
                        "allowances": (employee.allowances or 0),
                        "deductions": (Decimal("0.00")),
                        "payable_days": (
                            payable_days_map.get(
                                str(employee.id),
                                payable_days_map.get(
                                    employee.id,
                                ),
                            )
                        ),
                    }
                )

            serializer = PayrollEntrySerializer(
                data=payload,
                context={
                    "request": request,
                },
            )
            serializer.is_valid(raise_exception=True)
            created_entries.append(
                serializer.save(
                    payroll_run=run,
                    status="PAID",
                    paid_by=paid_by,
                    paid_at=timezone.now(),
                )
            )

        gross_total = sum(
            (Decimal(str(item.gross_salary or 0)) for item in created_entries),
            Decimal("0.00"),
        )
        deduction_total = sum(
            (Decimal(str(item.deductions or 0)) for item in created_entries),
            Decimal("0.00"),
        )
        advance_deduction_total = sum(
            (Decimal(str(item.advance_deduction or 0)) for item in created_entries),
            Decimal("0.00"),
        )
        net_total = sum(
            (Decimal(str(item.balance_payable or 0)) for item in created_entries),
            Decimal("0.00"),
        )

        run.total_gross = gross_total
        run.total_deductions = deduction_total
        run.total_advance_deduction = advance_deduction_total
        run.total_net = net_total
        run.status = "COMPLETED"
        run.save(
            update_fields=[
                "total_gross",
                "total_deductions",
                "total_advance_deduction",
                "total_net",
                "status",
                "updated_at",
            ]
        )

        return Response(
            self.get_serializer(run).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
    )
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
            advances=Sum("advance_amount"),
            advance_deductions=Sum("advance_deduction"),
            net=Sum("balance_payable"),
        )

        return Response(
            {
                "employees_on_payroll": (
                    entries.values("employee_id").distinct().count()
                ),
                "total_gross": (totals["gross"] or 0),
                "total_deductions": (totals["deductions"] or 0),
                "total_advances": (totals["advances"] or 0),
                "total_advance_deductions": (totals["advance_deductions"] or 0),
                "total_net": (totals["net"] or 0),
            }
        )

    @action(
        detail=False,
        methods=["get"],
    )
    def export(self, request):
        entries = PayrollEntry.objects.select_related(
            "employee",
            "branch",
            "paid_by",
        )
        period = request.query_params.get("period")
        branch_id = request.query_params.get("branch")

        if period:
            entries = entries.filter(period=period)

        if branch_id:
            entries = entries.filter(branch_id=branch_id)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; " 'filename="payroll.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Employee Code",
                "Employee",
                "Branch",
                "Period",
                "Payroll Date",
                "Salary Type",
                "Basic",
                "Allowances",
                "Gross",
                "Deductions",
                "Advance",
                "Advance Deducted",
                "Balance Payable",
                "Paid By",
                "Status",
            ]
        )

        for item in entries:
            writer.writerow(
                [
                    item.employee.employee_code,
                    item.employee.full_name,
                    (item.branch.branch_name if item.branch else ""),
                    item.period,
                    item.payroll_date,
                    item.get_salary_type_display(),
                    item.basic_salary,
                    item.allowances,
                    item.gross_salary,
                    item.deductions,
                    item.advance_amount,
                    item.advance_deduction,
                    item.balance_payable,
                    (
                        item.paid_by.get_full_name() or item.paid_by.username
                        if item.paid_by
                        else ""
                    ),
                    item.get_status_display(),
                ]
            )

        return response


class PayrollEntryViewSet(BaseViewSet):
    queryset = PayrollEntry.objects.select_related(
        "employee",
        "branch",
        "payroll_run",
        "paid_by",
    ).order_by(
        "-payroll_date",
        "-created_at",
        "-id",
    )
    serializer_class = PayrollEntrySerializer
    search_fields = [
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
        "period",
        "paid_by__first_name",
        "paid_by__last_name",
        "paid_by__username",
    ]
    filterset_fields = [
        "period",
        "branch",
        "status",
        "employee",
        "salary_type",
        "payroll_date",
        "paid_by",
    ]

    @action(
        detail=False,
        methods=["get"],
        url_path="form-options",
    )
    def form_options(self, request):
        User = get_user_model()

        users = User.objects.all()

        if any(field.name == "is_active" for field in User._meta.get_fields()):
            active_users = users.filter(is_active=True)

            if active_users.exists():
                users = active_users

        options = []

        for user in users:
            name = (
                (
                    user.get_full_name()
                    if hasattr(
                        user,
                        "get_full_name",
                    )
                    else ""
                )
                or getattr(
                    user,
                    "username",
                    "",
                )
                or getattr(
                    user,
                    "email",
                    "",
                )
                or f"User #{user.pk}"
            )

            options.append(
                {
                    "id": user.pk,
                    "name": name,
                    "is_current_user": (
                        request.user.is_authenticated and user.pk == request.user.pk
                    ),
                }
            )

        return Response(
            {
                "success": True,
                "message": ("Payroll entry form options loaded."),
                "data": {
                    "paid_by_users": options,
                },
            }
        )

    @transaction.atomic
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-paid",
    )
    def mark_paid(
        self,
        request,
        pk=None,
    ):
        entry = self.get_object()

        if entry.status == "PAID":
            return Response(self.get_serializer(entry).data)

        if entry.status in {
            "CANCELLED",
            "FAILED",
        }:
            return Response(
                {
                    "status": (
                        "Cancelled or failed payroll " "entries cannot be marked paid."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_by_id = request.data.get("paid_by")

        if not paid_by_id:
            return Response(
                {"paid_by": ("Paid By is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paid_by = (
            get_user_model()
            .objects.filter(
                pk=paid_by_id,
            )
            .first()
        )

        if not paid_by:
            return Response(
                {"paid_by": ("Selected payer was not found.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        entry.status = "PAID"
        entry.paid_by = paid_by
        entry.paid_at = timezone.now()
        entry.save(
            update_fields=[
                "status",
                "paid_by",
                "paid_at",
                "updated_at",
            ]
        )

        payroll_run = entry.payroll_run

        if payroll_run:
            pending_exists = (
                payroll_run.entries.exclude(status="PAID")
                .exclude(status="CANCELLED")
                .exists()
            )

            if not pending_exists:
                payroll_run.status = "COMPLETED"
                payroll_run.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

        entry.refresh_from_db()

        return Response(
            {
                "success": True,
                "message": ("Payroll entry marked as paid."),
                "data": self.get_serializer(entry).data,
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
