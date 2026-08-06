from rest_framework.routers import DefaultRouter

from .views import ServiceJobViewSet

router = DefaultRouter()
router.register("jobs", ServiceJobViewSet, basename="service-job")

urlpatterns = router.urls
