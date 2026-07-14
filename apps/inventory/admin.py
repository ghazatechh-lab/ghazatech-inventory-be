from django.contrib import admin
from .models import *

admin.site.register([Brand, Category, ProductStock, StockMovement, StockAdjustment])


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "product_name",
        "brand",
        "category",
        "retail_price",
        "is_active",
    )
    search_fields = ("sku", "barcode", "product_name")
    list_filter = ("brand", "category", "is_active")
