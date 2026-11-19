from rest_framework import serializers

from apps.accounts.models import User
from apps.audit.models import AuditLog


class AdminUserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    admin_level_label = serializers.CharField(source="get_admin_level_display", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone_number",
            "full_name",
            "first_name",
            "last_name",
            "role",
            "role_label",
            "admin_level",
            "admin_level_label",
            "is_active",
            "is_frozen",
            "is_email_verified",
            "is_phone_verified",
            "date_joined",
            "last_login",
        )
        read_only_fields = fields


class FreezeSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=1000, trim_whitespace=True)


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "created_at",
            "action",
            "entity_type",
            "entity_id",
            "actor",
            "actor_email",
            "before",
            "after",
            "reason",
            "request_id",
            "ip_address",
        )
        read_only_fields = fields


def customer_summary(user) -> dict:
    """User, profile, KYC, trust and risk in one place, for admin review screens."""
    from apps.accounts.profiles import get_profile_data
    from apps.kyc.models import kyc_status_for
    from apps.risk_engine.views import risk_payload
    from apps.trust_engine.views import trust_payload

    return {
        **AdminUserSerializer(user).data,
        "kyc_status": kyc_status_for(user),
        "profile": get_profile_data(user),
        "trust": trust_payload(user, history_limit=15) if user.role == "BORROWER" else None,
        "risk": risk_payload(user, include_override_details=True),
    }


class RoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["BORROWER", "INVESTOR", "GUARANTOR", "ADMIN"])
    admin_level = serializers.ChoiceField(choices=["NONE", "SUPPORT", "OPERATIONS", "FINANCE", "SUPER"],
                                          default="NONE")
    reason = serializers.CharField(min_length=10, max_length=1000)


class TrustAdjustSerializer(serializers.Serializer):
    points = serializers.IntegerField(min_value=-100, max_value=100)
    reason = serializers.CharField(min_length=10, max_length=1000)


class RiskOverrideSerializer(serializers.Serializer):
    classification = serializers.ChoiceField(
        choices=["", "VERY_LOW", "LOW", "MEDIUM", "HIGH", "CRITICAL"], allow_blank=True,
        help_text="Empty to clear the override and use the calculated classification.",
    )
    reason = serializers.CharField(min_length=10, max_length=1000)


class ConfigChangeSerializer(serializers.Serializer):
    parameters = serializers.JSONField()
    reason = serializers.CharField(min_length=10, max_length=1000)


class BracketChangeSerializer(serializers.Serializer):
    brackets = serializers.ListField(child=serializers.DictField(), allow_empty=False)
    rate_basis = serializers.ChoiceField(choices=["MONTHLY", "ANNUAL", "PER_LOAN"], required=False)
    reason = serializers.CharField(min_length=10, max_length=1000)
