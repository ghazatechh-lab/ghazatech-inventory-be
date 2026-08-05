from django.contrib import admin

from .models import (
    Brand,
    Category,
    Product,
    ProductStock,
    ProductVariant,
    Rack,
    StockAdjustment,
    StockMovement,
)

admin.site.register([Brand, Category, ProductStock, StockMovement, StockAdjustment])


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ("rack_code", "rack_name", "branch", "is_active")
    search_fields = ("rack_code", "rack_name", "branch__branch_name")
    list_filter = ("branch", "is_active")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = (
        "attributes",
        "available_qty",
        "purchase_price",
        "retail_price",
        "wholesale_price",
        "minimum_selling_price",
        "is_base",
        "is_active",
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "product_name",
        "brand",
        "category",
        "branch",
        "rack",
        "has_variants",
        "total_available_qty",
        "is_active",
    )
    search_fields = ("sku", "barcode", "product_name")
    list_filter = (
        "brand",
        "category",
        "branch",
        "rack",
        "tax_treatment",
        "has_variants",
        "is_active",
    )
    inlines = [ProductVariantInline]

    @admin.display(description="Available Qty")
    def total_available_qty(self, obj):
        return sum(stock.available_stock for stock in obj.stocks.all())
