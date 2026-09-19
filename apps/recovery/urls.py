from rest_framework.routers import DefaultRouter

from .views import RecoveryRecordViewSet, RecoverySettingsViewSet

router = DefaultRouter()
router.register("records", RecoveryRecordViewSet, basename="recovery-record")
router.register("settings", RecoverySettingsViewSet, basename="recovery-settings")

urlpatterns = router.urls
