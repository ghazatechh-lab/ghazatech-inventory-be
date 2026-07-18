from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Branch

User = get_user_model()


class BranchManagerOptionSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    role_name = serializers.CharField(
        source="role.name", read_only=True, allow_null=True
    )

    class Meta:
        model = User
        fields = ["id", "display_name", "email", "username", "role_name"]

    def get_display_name(self, obj):
        return obj.full_name or obj.get_full_name() or obj.username or obj.email


class BranchSerializer(serializers.ModelSerializer):
    manager = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    manager_detail = BranchManagerOptionSerializer(source="manager", read_only=True)

    class Meta:
        model = Branch
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at"]

    def to_internal_value(self, data):
        mutable_data = data.copy()

        # The frontend may submit an empty string when "No manager" is selected.
        # Convert it to None so the nullable ForeignKey validates correctly.
        if mutable_data.get("manager") in ("", "null", "undefined"):
            mutable_data["manager"] = None

        return super().to_internal_value(mutable_data)
