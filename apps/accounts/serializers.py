from rest_framework import serializers

from .models import User
from .permissions import permissions_for


class UserSerializer(serializers.ModelSerializer):
    """
    Read model for the authenticated user. Mirrors
    `mobile/lib/features/auth/data/user.dart` and the web app's session.

    `permissions` is computed server-side from role, admin level and account
    state; clients use it only to decide what to show.
    """

    full_name = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    admin_level_label = serializers.CharField(source="get_admin_level_display", read_only=True)
    permissions = serializers.SerializerMethodField()
    kyc_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone_number",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "role_label",
            "admin_level",
            "admin_level_label",
            "is_email_verified",
            "is_phone_verified",
            "is_frozen",
            "date_joined",
            "permissions",
            "kyc_status",
        )
        read_only_fields = fields

    def get_permissions(self, obj) -> list[str]:
        return sorted(permissions_for(obj))

    def get_kyc_status(self, obj) -> str:
        """NOT_SUBMITTED, PENDING, APPROVED or REJECTED."""
        from apps.kyc.models import kyc_status_for

        return kyc_status_for(obj)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Fields a user may change themselves. Email and phone changes need OTP (Phase 2)."""

    first_name = serializers.CharField(max_length=150, allow_blank=False, trim_whitespace=True)
    last_name = serializers.CharField(max_length=150, allow_blank=False, trim_whitespace=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name")
