from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.reports.views import reports_dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/branches/", include("apps.branches.urls")),
    path("api/", include("apps.inventory.urls")),
    path("api/customers/", include("apps.customers.urls")),
    path("api/suppliers/", include("apps.suppliers.urls")),
    path("api/sales/", include("apps.sales.urls")),
    path("api/purchases/", include("apps.purchases.urls")),
    path("api/hrms/", include("apps.hrms.urls")),
    path("api/finance/", include("apps.finance.urls")),
    path("api/transfers/", include("apps.transfers.urls")),
    path("api/shipments/", include("apps.shipments.urls")),
    path("api/service-repairs/", include("apps.service_repairs.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/audit-logs/", include("apps.audit_logs.urls")),
    path("api/reports/", include("apps.reports.urls")),
    path("api/dashboard/", reports_dashboard, name="reports-dashboard"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
