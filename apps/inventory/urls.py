from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ProductViewSet,
    BrandViewSet,
    CategoryViewSet,
    StockViewSet,
    StockMovementViewSet,
    StockAdjustmentViewSet,
    low_stock_products,
)

r = DefaultRouter()
r.register("products", ProductViewSet, basename="product")
r.register("brands", BrandViewSet, basename="brand")
r.register("categories", CategoryViewSet, basename="category")
r.register("inventory/stock", StockViewSet, basename="stock")
r.register("inventory/movements", StockMovementViewSet, basename="movement")
r.register("inventory/adjustments", StockAdjustmentViewSet, basename="adjustment")


urlpatterns = [
    path("inventory/low-stock/", low_stock_products, name="inventory-low-stock"),
]

urlpatterns += r.urls
