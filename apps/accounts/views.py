from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from .serializers import LoginSerializer, UserSerializer, ChangePasswordSerializer
from apps.common.response import ok


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        print(
            "Request data:", request.data
        )  # Debugging line to check the incoming request data
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        u = s.validated_data["user"]
        refresh = RefreshToken.for_user(u)
        return ok(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(u).data,
            },
            "Login successful",
        )


class LogoutView(APIView):
    def post(self, request):
        token = request.data.get("refresh")
        if token:
            RefreshToken(token).blacklist()
        return ok(message="Logged out successfully")


class MeView(APIView):
    def get(self, request):
        return ok(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    def post(self, request):
        s = ChangePasswordSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        request.user.set_password(s.validated_data["new_password"])
        request.user.save()
        return ok(message="Password changed successfully")


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return ok(
            message="Password reset flow placeholder created; connect email provider before production."
        )


class ResetPasswordView(ForgotPasswordView):
    pass
