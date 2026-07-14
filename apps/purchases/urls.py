from rest_framework.routers import DefaultRouter

from .views import (
    PurchaseOrderViewSet,
    GRNViewSet,
    SupplierBillViewSet,
    SupplierPaymentViewSet,
    SupplierReturnViewSet,
)

r = DefaultRouter()

# Purchase order routes
r.register("orders", PurchaseOrderViewSet, basename="purchase-order")
r.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order-alt")

# GRN routes
r.register("grn", GRNViewSet, basename="grn")
r.register("grns", GRNViewSet, basename="grn-alt")

# Supplier finance routes
r.register("supplier-bills", SupplierBillViewSet, basename="supplier-bill")
r.register("supplier-payments", SupplierPaymentViewSet, basename="supplier-payment")
r.register("supplier-returns", SupplierReturnViewSet, basename="supplier-return")

urlpatterns = r.urls
