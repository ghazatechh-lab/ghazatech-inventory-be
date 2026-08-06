from django.contrib import admin

from .models import ServiceCharge, ServiceJob


class ServiceChargeInline(admin.TabularInline):
    model = ServiceCharge
    extra = 0


@admin.register(ServiceJob)
class ServiceJobAdmin(admin.ModelAdmin):
    list_display = (
        "job_number",
        "customer_name",
        "brand",
        "model",
        "status",
        "technician",
        "branch",
        "created_at",
    )
    list_filter = ("status", "priority", "payment_status", "branch", "brand")
    search_fields = (
        "job_number",
        "customer_name",
        "phone",
        "serial_number",
        "brand",
        "model",
    )
    inlines = [ServiceChargeInline]
