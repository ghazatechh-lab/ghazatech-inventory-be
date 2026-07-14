from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class A(admin.ModelAdmin):
    list_display = ("created_at", "user", "module", "action", "branch")
    readonly_fields = ("created_at", "updated_at")
