from apps.common.logging import LoggedAPIView as APIView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import ChangePasswordSerializer, LoginSerializer, UserSerializer
from apps.common.response import ok


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
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return ok(
                {
                    "refresh": ["Refresh token is required."],
                },
                "Refresh token is required",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            # Logout remains idempotent: an expired/already-blacklisted token
            # should not prevent the client from completing local logout.
            return ok(message="Logged out successfully")

        return ok(message="Logged out successfully")


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return ok(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return ok(message="Password changed successfully")


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return ok(
            message=(
                "Password reset flow placeholder created; "
                "connect email provider before production."
            )
        )


class ResetPasswordView(ForgotPasswordView):
    pass
