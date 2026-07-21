from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    BrandViewSet,
    CategoryViewSet,
    ProductViewSet,
    RackViewSet,
    StockAdjustmentViewSet,
    StockMovementViewSet,
    StockViewSet,
    low_stock_products,
)

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("brands", BrandViewSet, basename="brand")
router.register("categories", CategoryViewSet, basename="category")
router.register("racks", RackViewSet, basename="rack")
router.register("inventory/stock", StockViewSet, basename="stock")
router.register("inventory/movements", StockMovementViewSet, basename="movement")
router.register("inventory/adjustments", StockAdjustmentViewSet, basename="adjustment")

urlpatterns = [
    path("inventory/low-stock/", low_stock_products, name="inventory-low-stock")
]
urlpatterns += router.urls
