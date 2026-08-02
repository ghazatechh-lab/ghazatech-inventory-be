from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import *

router = DefaultRouter()
router.register("departments", DepartmentViewSet, basename="department")
router.register("designations", DesignationViewSet, basename="designation")
router.register("employees", EmployeeViewSet, basename="employee")
router.register("documents", EmployeeDocumentViewSet, basename="employee-document")
router.register("attendance", AttendanceViewSet, basename="attendance")
router.register("leave-types", LeaveTypeViewSet, basename="leave-type")
router.register("leave-balances", LeaveBalanceViewSet, basename="leave-balance")
router.register("leaves", LeaveRequestViewSet, basename="leave-request")
router.register("salary-revisions", SalaryRevisionViewSet, basename="salary-revision")
router.register("payroll-runs", PayrollRunViewSet, basename="payroll-run")
router.register("payroll", PayrollEntryViewSet, basename="payroll-entry")
router.register("salary-advances", SalaryAdvanceViewSet, basename="salary-advance")
router.register("document-expiry", DocumentExpiryViewSet, basename="document-expiry")
router.register("reports", HRMSReportViewSet, basename="hrms-report")

urlpatterns = [path("", include(router.urls))]
