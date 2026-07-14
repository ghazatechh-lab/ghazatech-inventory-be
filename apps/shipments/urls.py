from rest_framework.routers import DefaultRouter
from .views import ShipmentViewSet

r = DefaultRouter()
r.register("", ShipmentViewSet, basename="shipment")
urlpatterns = r.urls
