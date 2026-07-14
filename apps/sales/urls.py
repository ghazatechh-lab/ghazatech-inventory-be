from rest_framework.routers import DefaultRouter
from .views import *

r = DefaultRouter()
r.register("quotations", QuotationViewSet)
r.register("invoices", InvoiceViewSet)
r.register("credit-notes", CreditNoteViewSet)
r.register("payments", PaymentViewSet)
urlpatterns = r.urls
