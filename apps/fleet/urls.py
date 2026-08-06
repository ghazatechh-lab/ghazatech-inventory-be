from rest_framework.routers import DefaultRouter
from .views import VehicleViewSet, VehicleTripViewSet

router = DefaultRouter()
router.register("vehicles", VehicleViewSet, basename="fleet-vehicle")
router.register("trips", VehicleTripViewSet, basename="fleet-trip")
urlpatterns = router.urls
