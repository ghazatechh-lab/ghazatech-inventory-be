from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from apps.hrms.models import Employee
from .models import Role
from .permission_catalog import PERMISSION_GROUPS, all_permission_codes

LEGACY_ACTION_MAP = {
    "add": "create",
    "create": "create",
    "change": "edit",
    "update": "edit",
    "edit": "edit",
    "remove": "delete",
    "delete": "delete",
    "read": "view",
    "view": "view",
    "approve": "approve",
    "reject": "reject",
    "cancel": "cancel",
    "convert": "convert",
    "export": "export",
    "print": "print",
    "process": "process",
    "activate": "activate",
    "close": "close",
}


def normalize_role_permissions(value, *, strict=True):
    """
    Return a clean list of complete operation permission codes.

    Existing databases may contain legacy values such as:
    ["view", "add", "edit", "all_access"].

    strict=True:
        Used while creating/updating a role. Truly unknown values are rejected.

    strict=False:
        Used while serializing existing roles. Unknown legacy values are ignored
        so GET /roles/ and GET /users/form-options/ never fail with HTTP 400.
    """
    valid_codes = set(all_permission_codes())

    if value in (None, "", [], {}):
        return []

    if isinstance(value, str):
        raw_value = value.strip()

        if not raw_value:
            return []

        try:
            import json

            decoded = json.loads(raw_value)
        except (TypeError, ValueError):
            decoded = [item.strip() for item in raw_value.split(",") if item.strip()]

        return normalize_role_permissions(
            decoded,
            strict=strict,
        )

    if isinstance(value, dict):
        if value.get("all_access") is True:
            return sorted(valid_codes)

        flattened = []

        def visit(node, path=None):
            path = path or []

            if node is True:
                if path:
                    flattened.append(".".join(path))
                return

            if node in (False, None, ""):
                return

            if isinstance(node, str):
                normalized = node.strip()

                if normalized:
                    if path and normalized.lower() in {
                        "true",
                        "yes",
                        "1",
                    }:
                        flattened.append(".".join(path))
                    else:
                        flattened.append(normalized)
                return

            if isinstance(node, dict):
                for key, child in node.items():
                    visit(child, [*path, str(key).strip()])
                return

            if isinstance(node, (list, tuple, set)):
                for item in node:
                    if isinstance(item, dict):
                        code = (
                            item.get("code")
                            or item.get("permission_code")
                            or item.get("permission")
                            or item.get("name")
                        )

                        if code:
                            flattened.append(str(code).strip())
                        else:
                            visit(item, path)
                    else:
                        visit(item, path)

        visit(value)
        value = flattened

    if not isinstance(value, (list, tuple, set)):
        if strict:
            raise serializers.ValidationError(
                "Permissions must be a list, object, or JSON string."
            )

        return []

    normalized = set()
    unknown = []

    for item in value:
        if isinstance(item, dict):
            item = (
                item.get("code")
                or item.get("permission_code")
                or item.get("permission")
                or item.get("name")
            )

        permission = str(item or "").strip()

        if not permission:
            continue

        permission_lower = permission.lower()

        if permission_lower in {
            "*",
            "all",
            "all_access",
            "full_access",
        }:
            return sorted(valid_codes)

        if permission in valid_codes:
            normalized.add(permission)
            continue

        mapped_action = LEGACY_ACTION_MAP.get(
            permission_lower,
            permission_lower,
        )

        # Legacy action-only permission such as "view" or "add".
        if "." not in mapped_action:
            matches = {
                code for code in valid_codes if code.rsplit(".", 1)[-1] == mapped_action
            }

            if matches:
                normalized.update(matches)
                continue

        # Handle a complete code whose final action uses an old name.
        parts = permission_lower.split(".")

        if len(parts) == 3:
            module_name, resource_name, action_name = parts

            candidate = ".".join(
                [
                    module_name,
                    resource_name,
                    LEGACY_ACTION_MAP.get(action_name, action_name),
                ]
            )

            if candidate in valid_codes:
                normalized.add(candidate)
                continue

        unknown.append(permission)

    if unknown and strict:
        raise serializers.ValidationError(
            "Unknown permissions: " + ", ".join(sorted(set(unknown)))
        )

    return sorted(normalized)


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
        return normalize_role_permissions(
            value,
            strict=True,
        )

    def validate(self, attrs):
        code = attrs.get(
            "code",
            getattr(self.instance, "code", ""),
        )

        if code == "ADMIN":
            attrs["permissions"] = all_permission_codes()

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.code == "ADMIN":
            data["permissions"] = all_permission_codes()
        else:
            data["permissions"] = normalize_role_permissions(
                instance.permissions,
                strict=False,
            )

        return data


class EmployeeUserOptionSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    branch_name = serializers.CharField(
        source="branch.branch_name", read_only=True, allow_null=True
    )
    user_id = serializers.IntegerField(
        source="user.id", read_only=True, allow_null=True
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
        write_only=True, required=False, allow_blank=False, min_length=8
    )
    role_name = serializers.CharField(
        source="role.name", read_only=True, allow_null=True
    )
    role_code = serializers.SerializerMethodField()
    role_detail = serializers.SerializerMethodField()
    branch_detail = serializers.SerializerMethodField()
    employee_detail = serializers.SerializerMethodField()
    employee_code = serializers.CharField(
        source="employee.employee_code", read_only=True, allow_null=True
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
        read_only_fields = ["is_staff", "is_superuser", "created_at", "updated_at"]
        extra_kwargs = {
            "employee": {"required": False, "allow_null": True},
            "role": {"required": True, "allow_null": False},
            "branch": {"required": False, "allow_null": True},
        }

    def get_role_code(self, obj):
        if obj.is_superuser:
            return "ADMIN"
        return obj.role.code if obj.role else None

    def get_role_detail(self, obj):
        if obj.is_superuser and not obj.role:
            return {"id": None, "name": "Super Admin", "code": "ADMIN"}
        if not obj.role:
            return None
        return {"id": obj.role.id, "name": obj.role.name, "code": obj.role.code}

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

    def get_permissions(self, obj):
        return obj.permission_codes

    def validate(self, attrs):
        role = attrs.get("role", getattr(self.instance, "role", None))
        employee = attrs.get("employee", getattr(self.instance, "employee", None))

        if role and role.code != "ADMIN" and not employee:
            raise serializers.ValidationError(
                {"employee": "Employee code is required for non-admin users."}
            )

        if employee:
            conflict = User.objects.filter(employee=employee)
            if self.instance:
                conflict = conflict.exclude(pk=self.instance.pk)
            if conflict.exists():
                raise serializers.ValidationError(
                    {"employee": "This employee is already linked to another user."}
                )

            branch = attrs.get("branch", getattr(self.instance, "branch", None))
            if not branch and employee.branch_id:
                attrs["branch"] = employee.branch

            if not attrs.get("full_name"):
                attrs["full_name"] = employee.full_name

        if role and role.code == "ADMIN":
            attrs["employee"] = None

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Password is required."})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class LoginSerializer(serializers.Serializer):
    email_or_username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.CharField(required=False, allow_blank=True)
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=True)

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
                {"email_or_username": "Email or username is required"}
            )
        user = User.objects.filter(
            Q(username__iexact=identity) | Q(email__iexact=identity)
        ).first()
        if not user or not user.check_password(password):
            raise serializers.ValidationError({"message": "Invalid credentials"})
        if not user.is_active:
            raise serializers.ValidationError({"message": "User account is inactive"})
        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Incorrect password")
        return value
