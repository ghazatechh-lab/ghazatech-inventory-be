from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("orders", SalesOrderViewSet, basename="sales-order")
router.register("invoices", SalesInvoiceViewSet, basename="sales-invoice")
router.register("pos", POSSaleViewSet, basename="pos-sale")
router.register("credit-notes", SalesCreditNoteViewSet, basename="credit-note")
router.register("payments", SalesPaymentViewSet, basename="sales-payment")
router.register("returns", SalesReturnViewSet, basename="sales-return")
router.register("price-lists", PriceListViewSet, basename="price-list")
router.register("reports", SalesReportViewSet, basename="sales-report")
urlpatterns = router.urls
