from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.logging import LoggedAPIView as APIView
from apps.common.response import ok
from apps.hrms.models import Employee
from .models import Role
from .permission_catalog import PERMISSION_GROUPS
from .serializers import (
    ChangePasswordSerializer,
    EmployeeUserOptionSerializer,
    LoginSerializer,
    RoleSerializer,
    UserSerializer,
)

User = get_user_model()


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        return ok(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            "Login successful",
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("refresh")
        if not token:
            return ok(
                {"refresh": ["Refresh token is required."]},
                "Refresh token is required",
                status_code=400,
            )
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            pass
        return ok(message="Logged out successfully")


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return ok(UserSerializer(request.user, context={"request": request}).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return ok(message="Password changed successfully")


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return ok(
            message="Password reset flow placeholder created; connect email provider before production."
        )


class ResetPasswordView(ForgotPasswordView):
    pass


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    search_fields = ["name", "code", "description"]
    ordering_fields = ["name", "code", "is_active"]

    def get_queryset(self):
        return Role.objects.annotate(user_count=Count("users")).order_by("name")

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()
        if role.code == "ADMIN":
            return Response({"detail": "The Admin role cannot be deleted."}, status=400)
        if role.users.exists():
            return Response(
                {"detail": "Move users to another role before deleting this role."},
                status=400,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="permission-catalog")
    def permission_catalog(self, request):
        return Response(PERMISSION_GROUPS)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    search_fields = [
        "email",
        "username",
        "full_name",
        "employee__employee_code",
        "employee__first_name",
        "employee__last_name",
    ]
    filterset_fields = ["role", "branch", "is_active"]
    ordering_fields = ["full_name", "email", "created_at", "is_active"]

    def get_queryset(self):
        return User.objects.select_related(
            "role", "branch", "employee", "employee__branch"
        ).order_by("full_name", "email")

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response(
                {"detail": "You cannot delete your own account."}, status=400
            )
        if user.is_superuser or (user.role and user.role.code == "ADMIN"):
            admins = (
                User.objects.filter(is_active=True).filter(role__code="ADMIN").count()
                + User.objects.filter(is_active=True, is_superuser=True)
                .exclude(role__code="ADMIN")
                .count()
            )
            if admins <= 1:
                return Response(
                    {"detail": "The final active administrator cannot be deleted."},
                    status=400,
                )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active"])
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response(
                {"detail": "You cannot deactivate your own account."}, status=400
            )
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(self.get_serializer(user).data)

    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        roles = Role.objects.filter(is_active=True).order_by("name")
        employees = (
            Employee.objects.select_related("branch")
            .filter(employment_status__in=["ACTIVE", "PROBATION", "ON_LEAVE"])
            .order_by("employee_code", "first_name")
        )
        employees = employees.filter(user__isnull=True)
        if request.query_params.get("include_employee"):
            employees = Employee.objects.select_related("branch").filter(
                Q(user__isnull=True) | Q(pk=request.query_params["include_employee"])
            )
        from apps.branches.models import Branch

        branches = Branch.objects.filter(is_active=True).order_by("branch_name")
        return Response(
            {
                "roles": RoleSerializer(roles, many=True).data,
                "employees": EmployeeUserOptionSerializer(employees, many=True).data,
                "branches": [
                    {
                        "id": x.id,
                        "branch_code": x.branch_code,
                        "branch_name": x.branch_name,
                    }
                    for x in branches
                ],
            }
        )
