from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_code", "customer_name", "phone", "is_active")
    search_fields = ("customer_code", "customer_name")
