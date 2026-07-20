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
        "default_variant_price",
        "is_active",
    )

    list_filter = (
        "brand",
        "category",
        "is_active",
    )

    search_fields = (
        "sku",
        "barcode",
        "product_name",
        "variants__sku",
        "variants__barcode",
    )

    def default_variant_price(self, obj):
        variant = (
            obj.variants.filter(
                is_default=True,
                is_active=True,
            ).first()
            or obj.variants.filter(is_active=True).first()
        )

        if not variant:
            return "—"

        return variant.retail_price

    default_variant_price.short_description = "Retail Price"
