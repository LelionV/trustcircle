"""
Role-specific profiles (borrower, investor, guarantor). Each user has at
most one, matching their role; it is created empty on first access.
"""
from django.db import transaction
from rest_framework import serializers

from apps.audit import services as audit
from apps.borrowers.models import BorrowerProfile
from apps.guarantors.models import GuarantorProfile
from apps.investors.models import InvestorProfile

from .models import Role

PROFILE_MODELS = {
    Role.BORROWER: BorrowerProfile,
    Role.INVESTOR: InvestorProfile,
    Role.GUARANTOR: GuarantorProfile,
}


def get_profile(user):
    model = PROFILE_MODELS.get(user.role)
    if model is None:
        return None
    profile, _ = model.objects.get_or_create(user=user)
    return profile


class _MoneyField(serializers.DecimalField):
    def __init__(self, **kwargs):
        super().__init__(max_digits=14, decimal_places=2, min_value=0, **kwargs)


class BorrowerProfileSerializer(serializers.ModelSerializer):
    monthly_income = _MoneyField(allow_null=True, required=False)
    monthly_obligations = _MoneyField(required=False)
    employment_status_label = serializers.CharField(source="get_employment_status_display", read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = BorrowerProfile
        fields = (
            "date_of_birth", "county", "town", "employment_status", "employment_status_label", "employer_name",
            "monthly_income", "monthly_obligations", "income_verified", "income_verified_at", "is_complete",
        )
        read_only_fields = ("income_verified", "income_verified_at")


class InvestorProfileSerializer(serializers.ModelSerializer):
    source_of_funds_label = serializers.CharField(source="get_source_of_funds_display", read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = InvestorProfile
        fields = ("date_of_birth", "county", "town", "occupation", "source_of_funds", "source_of_funds_label",
                  "is_complete")


class GuarantorProfileSerializer(serializers.ModelSerializer):
    monthly_income = _MoneyField(allow_null=True, required=False)
    employment_status_label = serializers.CharField(source="get_employment_status_display", read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = GuarantorProfile
        fields = (
            "date_of_birth", "county", "town", "employment_status", "employment_status_label", "employer_name",
            "monthly_income", "income_verified", "income_verified_at", "is_complete",
        )
        read_only_fields = ("income_verified", "income_verified_at")


PROFILE_SERIALIZERS = {
    Role.BORROWER: BorrowerProfileSerializer,
    Role.INVESTOR: InvestorProfileSerializer,
    Role.GUARANTOR: GuarantorProfileSerializer,
}

# Changing any of these after verification means the income must be checked again.
INCOME_FIELDS = ("monthly_income", "monthly_obligations", "employment_status", "employer_name")


def get_profile_data(user):
    profile = get_profile(user)
    if profile is None:
        return None
    return PROFILE_SERIALIZERS[user.role](profile).data


@transaction.atomic
def update_profile(user, data, request=None):
    profile = get_profile(user)
    serializer = PROFILE_SERIALIZERS[user.role](profile, data=data, partial=True)
    serializer.is_valid(raise_exception=True)
    changed = {k: v for k, v in serializer.validated_data.items() if getattr(profile, k) != v}
    if not changed:
        return profile
    before = {k: getattr(profile, k) for k in changed}
    income_reset = getattr(profile, "income_verified", False) and any(k in INCOME_FIELDS for k in changed)
    if income_reset:
        profile.income_verified = False
        profile.income_verified_at = None
    serializer.save()
    if income_reset:
        profile.save(update_fields=["income_verified", "income_verified_at"])
    audit.record(
        action="user.profile.details_updated",
        entity_type="User",
        entity_id=user.pk,
        actor=user,
        before=before,
        after={**changed, **({"income_verified": False} if income_reset else {})},
        request=request,
    )
    from apps.risk_engine.services import assess_risk
    from apps.trust_engine.services import recalculate_trust

    recalculate_trust(user, reason="Profile details changed")
    assess_risk(user, reason="Profile details changed")
    return profile
