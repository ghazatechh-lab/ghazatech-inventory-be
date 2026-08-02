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

SPECIAL_ACCESS_PERMISSION_CODES = {
    "sales.selling.regular",
    "sales.selling.restricted",
    "sales.selling.non_restricted",
    "sales.selling.vat",
    "sales.selling.non_vat",
    "sales.selling.discount",
    "sales.selling.price_override",
    "sales.vat.view",
    "sales.vat.manage",
    "sales.vat.override_rate",
    "sales.vat.use_zero_rated",
    "sales.vat.use_exempt",
    "sales.vat.use_out_of_scope",
    "sales.vat.use_reverse_charge",
    "sales.vat.view_reason",
    "sales.non_vat.view",
    "sales.non_vat.use",
    "sales.non_vat.manage",
    "inventory.stock_classification.view",
    "inventory.stock_classification.assign",
    "inventory.stock_classification.change",
    "inventory.restricted_stock.view",
    "inventory.restricted_stock.manage",
    "inventory.restricted_stock.sell",
    "inventory.restricted_stock.purchase",
    "inventory.restricted_stock.transfer",
    "inventory.restricted_stock.adjust",
    "inventory.non_restricted_stock.view",
    "inventory.non_restricted_stock.manage",
    "inventory.non_restricted_stock.sell",
    "inventory.non_restricted_stock.purchase",
    "inventory.non_restricted_stock.transfer",
    "inventory.non_restricted_stock.adjust",
    "purchases.stock_purchase.regular",
    "purchases.stock_purchase.restricted",
    "purchases.stock_purchase.non_restricted",
    "purchases.stock_purchase.vat",
    "purchases.stock_purchase.non_vat",
    "purchases.vat.view",
    "purchases.vat.manage",
    "purchases.vat.override_rate",
    "purchases.vat.use_zero_rated",
    "purchases.vat.use_exempt",
    "purchases.vat.use_out_of_scope",
    "purchases.vat.use_reverse_charge",
    "purchases.vat.view_reason",
    "purchases.non_vat.view",
    "purchases.non_vat.use",
    "purchases.non_vat.manage",
}


LEGACY_PERMISSION_ALIASES = {
    "dashboard.view": "dashboard.dashboard.view",
    "finance.view": "finance.*",
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


def normalize_permission_code(code):
    normalized = str(code or "").strip()

    return LEGACY_PERMISSION_ALIASES.get(
        normalized,
        normalized,
    )


def get_valid_permission_codes():
    """
    Return every permission accepted by the role form.

    The accounts permission catalogue remains the main source.
    Special-access codes are included directly so role saving does
    not fail when the frontend shows VAT, Non-VAT, selling, or
    stock-classification permissions.
    """
    valid = set(all_permission_codes())
    valid.update(SPECIAL_ACCESS_PERMISSION_CODES)
    valid.update(MODULE_WILDCARD_PERMISSIONS)

    try:
        from apps.common.permission_catalog import (
            iter_permission_codes,
        )

        valid.update(iter_permission_codes())
    except (
        ImportError,
        AttributeError,
    ):
        pass

    return sorted(valid)


User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    user_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "code",
            "description",
            "permissions",
            "is_active",
            "user_count",
        ]

    def validate_code(self, value):
        return str(value).strip().upper().replace(" ", "_")

    def validate_permissions(self, value):
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
                if str(permission).strip()
            }
        )

        valid = set(get_valid_permission_codes())

        invalid = sorted(set(normalized) - valid)

        if invalid:
            raise serializers.ValidationError(
                "Unknown permissions: " + ", ".join(invalid)
            )

        return normalized

    def validate(self, attrs):
        code = attrs.get(
            "code",
            getattr(
                self.instance,
                "code",
                "",
            ),
        )

        if code == "ADMIN":
            attrs["permissions"] = get_valid_permission_codes()

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.code == "ADMIN":
            data["permissions"] = get_valid_permission_codes()

        return data


class EmployeeUserOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
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
    permissions = serializers.SerializerMethodField()

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
            "is_active",
            "is_staff",
            "is_superuser",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "is_staff",
            "is_superuser",
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
            "branch_code": (obj.branch.branch_code),
            "branch_name": (obj.branch.branch_name),
        }

    def get_employee_detail(self, obj):
        if not obj.employee:
            return None

        return {
            "id": obj.employee.id,
            "employee_code": (obj.employee.employee_code),
            "full_name": (obj.employee.full_name),
            "branch": (obj.employee.branch_id),
        }

    def get_permissions(self, obj):
        return obj.permission_codes

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
            conflict = User.objects.filter(employee=employee)

            if self.instance:
                conflict = conflict.exclude(pk=self.instance.pk)

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

        if role and role.code == "ADMIN":
            attrs["employee"] = None

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
            setattr(
                instance,
                field,
                value,
            )

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
            raise serializers.ValidationError({"message": ("Invalid credentials")})

        if not user.is_active:
            raise serializers.ValidationError({"message": ("User account is inactive")})

        attrs["user"] = user

        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate_old_password(
        self,
        value,
    ):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Incorrect password")

        return value
