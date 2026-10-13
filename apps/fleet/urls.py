from rest_framework.routers import DefaultRouter
from .views import VehicleDocumentViewSet, VehicleViewSet, VehicleTripViewSet

router = DefaultRouter()
router.register("vehicles", VehicleViewSet, basename="fleet-vehicle")
router.register("trips", VehicleTripViewSet, basename="fleet-trip")
router.register("vehicle-documents", VehicleDocumentViewSet, basename="fleet-vehicle-document")
urlpatterns = router.urls
