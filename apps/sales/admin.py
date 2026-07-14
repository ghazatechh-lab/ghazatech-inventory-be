from django.contrib import admin
from .models import *


class QInline(admin.TabularInline):
    model = QuotationItem
    extra = 0


@admin.register(Quotation)
class QA(admin.ModelAdmin):
    inlines = [QInline]
    list_display = ("quotation_number", "customer", "branch", "status", "total_amount")


class IInline(admin.TabularInline):
    model = SalesInvoiceItem
    extra = 0


@admin.register(SalesInvoice)
class IA(admin.ModelAdmin):
    inlines = [IInline]
    list_display = (
        "invoice_number",
        "customer",
        "branch",
        "total_amount",
        "payment_status",
        "is_confirmed",
    )


admin.site.register([SalesCreditNote, SalesPayment])
