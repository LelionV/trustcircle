from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.serializers import UserSerializer


class PlatformTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login with email + password. Returns access/refresh tokens plus the user
    profile so clients can route to the correct dashboard immediately.
    """

    default_error_messages = {
        "no_active_account": "Invalid email or password.",
    }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Informational only — the backend always re-reads roles from the DB.
        token["role"] = user.role
        return token

    def validate(self, attrs):
        attrs[self.username_field] = attrs.get(self.username_field, "").strip().lower()
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
        except TokenError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        user = self.context["request"].user
        if str(token.get("user_id")) != str(user.pk):
            raise serializers.ValidationError("Token does not belong to the current user.")
        self._token = token
        return value

    def save(self, **kwargs):
        try:
            self._token.blacklist()
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": [str(exc)]}) from exc


# --- Registration ---------------------------------------------------------------

class RegisterSerializer(serializers.Serializer):
    ROLE_CHOICES = [("BORROWER", "Borrower"), ("INVESTOR", "Investor"), ("GUARANTOR", "Guarantor")]

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=20)
    role = serializers.ChoiceField(choices=ROLE_CHOICES)

    def validate_email(self, value):
        from apps.accounts.models import User

        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists. Sign in instead.")
        return value

    def validate_phone_number(self, value):
        from apps.accounts.models import User
        from apps.common.phone import PhoneNumberError, normalize_phone

        if not value:
            return None
        try:
            phone = normalize_phone(value)
        except PhoneNumberError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        if User.objects.filter(phone_number=phone).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return phone

    def validate(self, attrs):
        from django.contrib.auth import password_validation
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.accounts.models import User

        candidate = User(email=attrs["email"], first_name=attrs["first_name"], last_name=attrs["last_name"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs


def tokens_for(user) -> dict:
    refresh = PlatformTokenObtainPairSerializer.get_token(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


# --- Verification codes -------------------------------------------------------------

class OtpRequestSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=[("EMAIL", "Email"), ("PHONE", "Phone")])


class OtpVerifySerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=[("EMAIL", "Email"), ("PHONE", "Phone")])
    code = serializers.RegexField(r"^\s*\d{4,8}\s*$", error_messages={"invalid": "Enter the code we sent you."})


class PhoneSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        from apps.common.phone import PhoneNumberError, normalize_phone

        try:
            return normalize_phone(value)
        except PhoneNumberError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Your current password isn't right.")
        return value

    def validate(self, attrs):
        from django.contrib.auth import password_validation
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            password_validation.validate_password(attrs["new_password"], self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs
