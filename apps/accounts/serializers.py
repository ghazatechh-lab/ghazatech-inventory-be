from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from apps.hrms.models import Employee

from .models import Role
from .permission_catalog import (
    PERMISSION_GROUPS,
    all_permission_codes,
)

LEGACY_PERMISSION_ALIASES = {
    "dashboard.view": "dashboard.dashboard.view",
    "finance.view": "accounting.*",
    "hrms.view": "hrms.*",
    "inventory.view": "inventory.*",
    "reports.view": "reports.*",
    "reports.export": "reports.*",
    "sales.view": "sales.*",
}


MODULE_WILDCARD_PERMISSIONS = {
    "*",
    "dashboard.*",
    "inventory.*",
    "purchase.*",
    "purchases.*",
    "sales.*",
    "accounting.*",
    "finance.*",
    "hrms.*",
    "reports.*",
    "settings.*",
}


OBSOLETE_PERMISSION_PREFIXES = (
    "inventory.stock_classification.",
    "inventory.restricted_stock.",
    "inventory.non_restricted_stock.",
    "sales.vat.",
    "sales.non_vat.",
    "purchases.vat.",
    "purchases.non_vat.",
)


OBSOLETE_PERMISSION_CODES = {
    "sales.selling.regular",
    "sales.selling.restricted",
    "sales.selling.non_restricted",
    "sales.selling.vat",
    "sales.selling.non_vat",
    "purchases.stock_purchase.regular",
    "purchases.stock_purchase.restricted",
    "purchases.stock_purchase.non_restricted",
    "purchases.stock_purchase.vat",
    "purchases.stock_purchase.non_vat",
}


def normalize_permission_code(code):
    normalized = str(code or "").strip()

    return LEGACY_PERMISSION_ALIASES.get(
        normalized,
        normalized,
    )


def is_obsolete_permission(code):
    normalized = normalize_permission_code(code)

    return normalized in OBSOLETE_PERMISSION_CODES or normalized.startswith(
        OBSOLETE_PERMISSION_PREFIXES
    )


def get_valid_permission_codes():
    valid = set(all_permission_codes())
    valid.update(MODULE_WILDCARD_PERMISSIONS)

    return sorted(valid)


def normalize_user_permissions(value):
    value = value or []

    if not isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        raise serializers.ValidationError("Permissions must be a list.")

    normalized = sorted(
        {
            normalize_permission_code(permission)
            for permission in value
            if str(permission).strip() and not is_obsolete_permission(permission)
        }
    )

    valid = set(get_valid_permission_codes())

    invalid = sorted(set(normalized) - valid)

    if invalid:
        raise serializers.ValidationError("Unknown permissions: " + ", ".join(invalid))

    return normalized


User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    user_count = serializers.IntegerField(
        read_only=True,
    )

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "code",
            "description",
            "is_active",
            "user_count",
        ]

    def validate_code(self, value):
        return str(value).strip().upper().replace(" ", "_")


class EmployeeUserOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(
        read_only=True,
    )

    branch_name = serializers.CharField(
        source="branch.branch_name",
        read_only=True,
        allow_null=True,
    )

    user_id = serializers.IntegerField(
        source="user.id",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_code",
            "full_name",
            "email",
            "branch",
            "branch_name",
            "user_id",
        ]


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=False,
        min_length=8,
    )

    role_name = serializers.CharField(
        source="role.name",
        read_only=True,
        allow_null=True,
    )

    role_code = serializers.SerializerMethodField()
    role_detail = serializers.SerializerMethodField()
    branch_detail = serializers.SerializerMethodField()
    employee_detail = serializers.SerializerMethodField()

    employee_code = serializers.CharField(
        source="employee.employee_code",
        read_only=True,
        allow_null=True,
    )

    # USER-LEVEL permissions: writable.
    permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )

    effective_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "password",
            "full_name",
            "phone_number",
            "profile_image",
            "employee",
            "employee_code",
            "employee_detail",
            "role",
            "role_name",
            "role_code",
            "role_detail",
            "branch",
            "branch_detail",
            "permissions",
            "effective_permissions",
            "is_active",
            "is_staff",
            "is_superuser",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "is_staff",
            "is_superuser",
            "effective_permissions",
            "created_at",
            "updated_at",
        ]

        extra_kwargs = {
            "employee": {
                "required": False,
                "allow_null": True,
            },
            "role": {
                "required": True,
                "allow_null": False,
            },
            "branch": {
                "required": False,
                "allow_null": True,
            },
        }

    def get_role_code(self, obj):
        if obj.is_superuser:
            return "ADMIN"

        return obj.role.code if obj.role else None

    def get_role_detail(self, obj):
        if obj.is_superuser and not obj.role:
            return {
                "id": None,
                "name": "Super Admin",
                "code": "ADMIN",
            }

        if not obj.role:
            return None

        return {
            "id": obj.role.id,
            "name": obj.role.name,
            "code": obj.role.code,
        }

    def get_branch_detail(self, obj):
        if not obj.branch:
            return None

        return {
            "id": obj.branch.id,
            "branch_code": obj.branch.branch_code,
            "branch_name": obj.branch.branch_name,
        }

    def get_employee_detail(self, obj):
        if not obj.employee:
            return None

        return {
            "id": obj.employee.id,
            "employee_code": obj.employee.employee_code,
            "full_name": obj.employee.full_name,
            "branch": obj.employee.branch_id,
        }

    def get_effective_permissions(self, obj):
        return obj.permission_codes

    def validate_permissions(self, value):
        return normalize_user_permissions(value)

    def validate(self, attrs):
        role = attrs.get(
            "role",
            getattr(
                self.instance,
                "role",
                None,
            ),
        )

        employee = attrs.get(
            "employee",
            getattr(
                self.instance,
                "employee",
                None,
            ),
        )

        if role and role.code != "ADMIN" and not employee:
            raise serializers.ValidationError(
                {"employee": ("Employee code is required " "for non-admin users.")}
            )

        if employee:
            conflict = User.objects.filter(
                employee=employee,
            )

            if self.instance:
                conflict = conflict.exclude(
                    pk=self.instance.pk,
                )

            if conflict.exists():
                raise serializers.ValidationError(
                    {
                        "employee": (
                            "This employee is already " "linked to another user."
                        )
                    }
                )

            branch = attrs.get(
                "branch",
                getattr(
                    self.instance,
                    "branch",
                    None,
                ),
            )

            if not branch and employee.branch_id:
                attrs["branch"] = employee.branch

            if not attrs.get("full_name"):
                attrs["full_name"] = employee.full_name

        # ADMIN is still unrestricted, but permission storage is kept clean.
        if role and role.code == "ADMIN":
            attrs["employee"] = None
            attrs["permissions"] = []

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop(
            "password",
            None,
        )

        if not password:
            raise serializers.ValidationError({"password": ("Password is required.")})

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        return user

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        password = validated_data.pop(
            "password",
            None,
        )

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if password:
            instance.set_password(password)

        instance.save()

        return instance


class LoginSerializer(serializers.Serializer):
    email_or_username = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    email = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    username = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    password = serializers.CharField(
        write_only=True,
        required=True,
    )

    def validate(self, attrs):
        identity = (
            attrs.get("email_or_username")
            or attrs.get("email")
            or attrs.get("username")
            or ""
        ).strip()

        password = attrs.get("password")

        if not identity:
            raise serializers.ValidationError(
                {"email_or_username": ("Email or username is required")}
            )

        user = User.objects.filter(
            Q(username__iexact=identity) | Q(email__iexact=identity)
        ).first()

        if not user or not user.check_password(password):
            raise serializers.ValidationError({"message": "Invalid credentials"})

        if not user.is_active:
            raise serializers.ValidationError({"message": ("User account is inactive")})

        attrs["user"] = user

        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(
        min_length=8,
    )

    def validate_old_password(
        self,
        value,
    ):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Incorrect password")

        return value
