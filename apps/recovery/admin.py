from django.contrib import admin

from .models import RecoveryRecord, RecoverySettings


@admin.register(RecoveryRecord)
class RecoveryRecordAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "record_name",
        "module",
        "status",
        "deleted_at",
        "expires_at",
    )
    list_filter = ("status", "module")
    search_fields = ("reference", "record_name", "object_id", "deletion_reason")
    readonly_fields = ("snapshot",)


@admin.register(RecoverySettings)
class RecoverySettingsAdmin(admin.ModelAdmin):
    pass
