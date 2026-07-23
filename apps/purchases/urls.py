from rest_framework.routers import DefaultRouter
from .views import (
    PurchaseOrderViewSet,
    GRNViewSet,
    SupplierBillViewSet,
    SupplierPaymentViewSet,
    SupplierReturnViewSet,
    VendorCreditViewSet,
    PurchaseExpenseViewSet,
)

r = DefaultRouter()
r.register("orders", PurchaseOrderViewSet, basename="purchase-order")
r.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order-alt")
r.register("grn", GRNViewSet, basename="grn")
r.register("grns", GRNViewSet, basename="grn-alt")
r.register("supplier-bills", SupplierBillViewSet, basename="supplier-bill")
r.register("supplier-payments", SupplierPaymentViewSet, basename="supplier-payment")
r.register("supplier-returns", SupplierReturnViewSet, basename="supplier-return")
r.register("vendor-credits", VendorCreditViewSet, basename="vendor-credit")
r.register("expenses", PurchaseExpenseViewSet, basename="purchase-expense")
urlpatterns = r.urls
