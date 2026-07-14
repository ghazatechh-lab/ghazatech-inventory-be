from rest_framework.routers import DefaultRouter
from .views import StockTransferViewSet

r = DefaultRouter()
r.register("", StockTransferViewSet, basename="transfer")

urlpatterns = r.urls
