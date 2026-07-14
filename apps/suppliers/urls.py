from rest_framework.routers import DefaultRouter
from .views import SupplierViewSet

r = DefaultRouter()
r.register("", SupplierViewSet, basename="supplier")
urlpatterns = r.urls
