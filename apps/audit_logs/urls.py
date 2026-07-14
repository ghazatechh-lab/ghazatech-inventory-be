from rest_framework.routers import DefaultRouter
from .views import AuditLogViewSet

r = DefaultRouter()
r.register("", AuditLogViewSet, basename="audit-log")
urlpatterns = r.urls
