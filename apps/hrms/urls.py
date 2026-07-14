from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeViewSet,
    AttendanceViewSet,
    LeaveViewSet,
    PayrollViewSet,
    DepartmentViewSet,
    DesignationViewSet,
    LeaveTypeViewSet,
    document_expiry,
)

r = DefaultRouter()
r.register("employees", EmployeeViewSet)
r.register("attendance", AttendanceViewSet)
r.register("leaves", LeaveViewSet)
r.register("payroll", PayrollViewSet)
r.register("departments", DepartmentViewSet)
r.register("designations", DesignationViewSet)
r.register("leave-types", LeaveTypeViewSet)

urlpatterns = [
    path("document-expiry/", document_expiry, name="hrms-document-expiry"),
    path(
        "document-expiry/upcoming/",
        document_expiry,
        name="hrms-document-expiry-upcoming",
    ),
]

urlpatterns += r.urls
