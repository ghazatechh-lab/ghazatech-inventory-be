from rest_framework import serializers

from .models import RecoveryRecord, RecoverySettings


class RecoveryRecordSerializer(serializers.ModelSerializer):
    deleted_by_name = serializers.SerializerMethodField()
    restored_by_name = serializers.SerializerMethodField()
    permanent_deleted_by_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.branch_name", read_only=True)
    expires_in_days = serializers.SerializerMethodField()
    can_restore = serializers.SerializerMethodField()
    can_permanently_delete = serializers.SerializerMethodField()

    class Meta:
        model = RecoveryRecord
        fields = [
            "id",
            "module",
            "model_name",
            "record_name",
            "reference",
            "object_id",
            "branch",
            "branch_name",
            "snapshot",
            "deletion_reason",
            "status",
            "deleted_at",
            "deleted_by",
            "deleted_by_name",
            "expires_at",
            "expires_in_days",
            "restored_at",
            "restored_by",
            "restored_by_name",
            "permanently_deleted_at",
            "permanently_deleted_by",
            "permanent_deleted_by_name",
            "can_restore",
            "can_permanently_delete",
        ]

    def _user_name(self, user):
        if not user:
            return "System"
        return user.full_name or user.get_full_name() or user.email or user.username

    def get_deleted_by_name(self, obj):
        return self._user_name(obj.deleted_by)

    def get_restored_by_name(self, obj):
        return self._user_name(obj.restored_by) if obj.restored_by else ""

    def get_permanent_deleted_by_name(self, obj):
        return self._user_name(obj.permanently_deleted_by) if obj.permanently_deleted_by else ""

    def get_expires_in_days(self, obj):
        if not obj.expires_at:
            return None
        from django.utils import timezone
        delta = obj.expires_at - timezone.now()
        return max(0, delta.days + (1 if delta.seconds > 0 else 0))

    def get_can_restore(self, obj):
        return obj.status == RecoveryRecord.STATUS_DELETED

    def get_can_permanently_delete(self, obj):
        return obj.status == RecoveryRecord.STATUS_DELETED


class RecoverySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecoverySettings
        exclude = ["created_at", "updated_at"]
