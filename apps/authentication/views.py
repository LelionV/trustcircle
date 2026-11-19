from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from django.db import transaction
from rest_framework.permissions import AllowAny

from apps.accounts.serializers import UserSerializer
from apps.audit import services as audit

from . import services
from .serializers import (
    LoginResponseSerializer,
    LogoutSerializer,
    OtpRequestSerializer,
    OtpVerifySerializer,
    PasswordChangeSerializer,
    PhoneSerializer,
    PlatformTokenObtainPairSerializer,
    RegisterSerializer,
    tokens_for,
)


class LoginView(TokenObtainPairView):
    """Exchange email + password for a JWT access/refresh pair."""

    serializer_class = PlatformTokenObtainPairSerializer
    throttle_scope = "auth"

    @extend_schema(responses=LoginResponseSerializer, tags=["auth"])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    """Rotate tokens. The submitted refresh token is blacklisted."""

    throttle_scope = "auth"

    @extend_schema(tags=["auth"])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class VerifyView(TokenVerifyView):
    @extend_schema(tags=["auth"])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    """Blacklist a refresh token so it can no longer be used."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=LogoutSerializer, responses={205: None}, tags=["auth"])
    def post(self, request):
        serializer = LogoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_205_RESET_CONTENT)


class RegisterView(APIView):
    """Create a borrower, investor or guarantor account and sign in."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth"

    @extend_schema(request=RegisterSerializer, responses={201: LoginResponseSerializer}, tags=["auth"])
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data, request=request)
        return Response({**tokens_for(user), "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class OtpRequestView(APIView):
    """Send a verification code to the user's email or phone."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "otp"

    @extend_schema(request=OtpRequestSerializer, tags=["auth"])
    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(services.request_code(request.user, serializer.validated_data["channel"]))


class OtpVerifyView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(request=OtpVerifySerializer, responses=UserSerializer, tags=["auth"])
    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.verify_code(
            request.user, serializer.validated_data["channel"], serializer.validated_data["code"], request=request
        )
        return Response(UserSerializer(user).data)


class PhoneView(APIView):
    """Add or change your phone number. A new number must be verified again."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=PhoneSerializer, responses=UserSerializer, tags=["auth"])
    def put(self, request):
        serializer = PhoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.change_phone(request.user, serializer.validated_data["phone_number"], request=request)
        return Response(UserSerializer(user).data)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    @extend_schema(request=PasswordChangeSerializer, responses={204: None}, tags=["auth"])
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        with transaction.atomic():
            user.set_password(serializer.validated_data["new_password"])
            user.save(update_fields=["password", "updated_at"])
            audit.record(action="user.password.changed", entity_type="User", entity_id=user.pk,
                         actor=user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
