from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Role
from django.db.models import Q

from .models import User


class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_code = serializers.SerializerMethodField()
    role_detail = serializers.SerializerMethodField()
    branch_detail = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "full_name",
            "phone_number",
            "profile_image",
            # Existing backend fields
            "role",
            "role_name",
            "branch",
            # Frontend-friendly fields
            "role_code",
            "role_detail",
            "branch_detail",
            "is_active",
            "is_staff",
            "is_superuser",
            "created_at",
        ]

    def get_role_code(self, obj):
        if obj.is_superuser:
            return "ADMIN"

        if not obj.role:
            return None

        role_code_map = {
            "Super Admin": "ADMIN",
            "Branch Manager": "BM",
            "Sales Manager": "SM",
            "Sales Executive": "SE",
            "Inventory Manager": "IM",
            "Purchase Manager": "PM",
            "Accountant": "ACC",
            "HR Manager": "HRM",
            "HR Executive": "HRE",
            "Warehouse Staff": "WS",
            "Viewer": "VIEWER",
        }

        return role_code_map.get(obj.role.name, obj.role.name.upper().replace(" ", "_"))

    def get_role_detail(self, obj):
        if not obj.role:
            if obj.is_superuser:
                return {
                    "id": None,
                    "name": "Super Admin",
                    "code": "ADMIN",
                }
            return None

        return {
            "id": obj.role.id,
            "name": obj.role.name,
            "code": self.get_role_code(obj),
        }

    def get_branch_detail(self, obj):
        if not obj.branch:
            return None

        return {
            "id": obj.branch.id,
            "branch_code": obj.branch.branch_code,
            "branch_name": obj.branch.branch_name,
        }


from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email_or_username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.CharField(required=False, allow_blank=True)
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        email_or_username = (
            attrs.get("email_or_username")
            or attrs.get("email")
            or attrs.get("username")
            or ""
        ).strip()

        password = attrs.get("password")

        print("Login attrs:", attrs)
        print("email_or_username:", email_or_username)

        if not email_or_username:
            raise serializers.ValidationError(
                {"email_or_username": "Email or username is required"}
            )

        if not password:
            raise serializers.ValidationError({"password": "Password is required"})

        user = User.objects.filter(
            Q(username__iexact=email_or_username) | Q(email__iexact=email_or_username)
        ).first()

        print("User found:", user)

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
