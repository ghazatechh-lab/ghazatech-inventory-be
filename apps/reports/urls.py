from django.urls import path

from .views import (
    inventory_report,
    purchase_report,
    reports_dashboard,
)

urlpatterns = [
    path("dashboard/", reports_dashboard, name="reports-dashboard"),
    path("purchases/", purchase_report, name="reports-purchases"),
    path("inventory/", inventory_report, name="reports-inventory"),
]
