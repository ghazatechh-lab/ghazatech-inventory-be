from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    BranchDatabaseProfileViewSet,
    MasterInventorySyncLogViewSet,
    combined_summary,
)

router = DefaultRouter()
router.register("profiles", BranchDatabaseProfileViewSet, basename="branch-db-profile")
router.register("sync-logs", MasterInventorySyncLogViewSet, basename="master-stock-sync")

urlpatterns = [
    path("combined-summary/", combined_summary, name="combined-summary"),
] + router.urls
