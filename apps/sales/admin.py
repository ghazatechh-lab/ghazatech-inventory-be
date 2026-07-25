from django.contrib import admin
from .models import Quotation,SalesOrder,SalesInvoice,POSSale,SalesCreditNote,SalesPayment,SalesReturn,PriceList,SalesReport
for model in [Quotation,SalesOrder,SalesInvoice,POSSale,SalesCreditNote,SalesPayment,SalesReturn,PriceList,SalesReport]: admin.site.register(model)
