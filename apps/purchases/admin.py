from django.contrib import admin
from .models import *

admin.site.register(
    [
        PurchaseOrder,
        PurchaseOrderItem,
        GoodsReceivedNote,
        GoodsReceivedItem,
        SupplierBill,
        SupplierPayment,
        SupplierReturn,
    ]
)
