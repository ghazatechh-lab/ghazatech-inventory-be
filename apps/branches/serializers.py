from uuid import uuid4
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
    branch_code = serializers.CharField(required=False, allow_blank=True, max_length=30)
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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        code = str(attrs.get("branch_code", getattr(self.instance, "branch_code", ""))).strip().upper()
        mode = attrs.get("tax_mode", getattr(self.instance, "tax_mode", ""))
        if self.instance and not self.instance.tax_mode:
            raise serializers.ValidationError("The consolidated virtual branch cannot be edited as a physical branch.")
        if mode not in (Branch.TAX_VAT, Branch.TAX_NON_VAT):
            raise serializers.ValidationError({"tax_mode": "Select VAT or Non-VAT."})
        if self.instance and mode != self.instance.tax_mode:
            from apps.branch_data.models import BranchDatabaseProfile
            if BranchDatabaseProfile.objects.using("default").filter(branch_id=self.instance.pk).exists():
                raise serializers.ValidationError({"tax_mode": "Cannot change a provisioned branch's tax type."})
        if not self.instance and code == "CONSOLIDATED":
            raise serializers.ValidationError({"branch_code": "Reserved for the consolidated view."})
        if code:
            attrs["branch_code"] = code
        return attrs

    def create(self, validated_data):
        # Opaque human-independent identifier; no fixed BR01/BR02 numbering.
        validated_data.setdefault("branch_code", "LOC-" + uuid4().hex[:12].upper())
        # Provisioning sets active=True only after schema creation and reference sync.
        validated_data["is_active"] = False
        return super().create(validated_data)

    def to_internal_value(self, data):
        mutable_data = data.copy()

        # The frontend may submit an empty string when "No manager" is selected.
        # Convert it to None so the nullable ForeignKey validates correctly.
        if mutable_data.get("manager") in ("", "null", "undefined"):
            mutable_data["manager"] = None

        return super().to_internal_value(mutable_data)
