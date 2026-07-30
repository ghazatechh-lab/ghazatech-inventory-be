from django.contrib import admin
from .models import (
    Quotation,
    SalesOrder,
    SalesInvoice,
    POSSale,
    SalesCreditNote,
    SalesPayment,
    SalesReturn,
    PriceList,
    SalesReport,
    DeliveryNote,
)

for model in [
    Quotation,
    SalesOrder,
    SalesInvoice,
    POSSale,
    SalesCreditNote,
    SalesPayment,
    SalesReturn,
    PriceList,
    SalesReport,
    DeliveryNote,
]:
    admin.site.register(model)
