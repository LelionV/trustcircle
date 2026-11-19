from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from . import calculators as calc
from .models import RiskAssessment, RiskConfig, RiskProfile


def active_config():
    return RiskConfig.active(calc.default_parameters)


def _inputs(user):
    from apps.accounts.profiles import get_profile
    from apps.kyc.models import kyc_status_for
    from apps.loans.models import OPEN_LOAN_STATUSES, Loan
    from apps.trust_engine.models import LoanOutcome, TrustScore

    profile = get_profile(user)
    trust = TrustScore.objects.filter(user=user).first()
    punctuality = None
    if trust and trust.breakdown:
        for row in trust.breakdown.get("components", []):
            if row["key"] == "punctuality":
                punctuality = row["score"]
    return calc.RiskInputs(
        kyc_status=kyc_status_for(user),
        punctuality_score=punctuality,
        monthly_income=getattr(profile, "monthly_income", None),
        monthly_obligations=getattr(profile, "monthly_obligations", Decimal("0")) or Decimal("0"),
        income_verified=getattr(profile, "income_verified", False),
        employment_status=getattr(profile, "employment_status", ""),
        defaults=LoanOutcome.objects.filter(user=user, outcome=LoanOutcome.Outcome.DEFAULTED).count(),
        open_loans=Loan.objects.filter(borrower=user, status__in=OPEN_LOAN_STATUSES).count(),
        is_frozen=user.is_frozen,
    )


@transaction.atomic
def assess_risk(user, reason="Risk reassessed"):
    """Borrowers and guarantors are assessed; investors and admins aren't."""
    if user.role not in (Role.BORROWER, Role.GUARANTOR):
        return None
    config = active_config()
    result = calc.calculate(_inputs(user), config.parameters)
    now = timezone.now()
    profile = RiskProfile.objects.select_for_update().filter(user=user).first()
    changed = profile is None or profile.score != result["score"] or profile.classification != result["classification"]
    if profile is None:
        profile = RiskProfile(user=user)
    profile.score = result["score"]
    profile.classification = result["classification"]
    profile.factors = result["factors"]
    profile.config = config
    profile.assessed_at = now
    profile.save()
    if changed:
        RiskAssessment.objects.create(
            user=user, score=result["score"], classification=result["classification"],
            factors=result["factors"], reason=reason[:255], config=config,
        )
    return profile


@transaction.atomic
def override_classification(*, actor, user, classification, reason, request=None):
    """Set (or clear, with an empty classification) a manual risk classification."""
    if user.pk == actor.pk:
        raise BusinessRuleViolation("You can't override your own risk rating.", code="self_action")
    profile = RiskProfile.objects.select_for_update().filter(user=user).first() or assess_risk(user, "Assessed for override")
    if profile is None:
        raise BusinessRuleViolation("Only borrowers and guarantors have risk ratings.", code="no_risk_profile")
    if classification and classification not in calc.CLASSES:
        raise BusinessRuleViolation("Choose a valid risk classification.", code="bad_class")
    before = {"override": profile.override_classification or None, "calculated": profile.classification}
    profile.override_classification = classification or ""
    profile.override_reason = reason if classification else ""
    profile.override_by = actor if classification else None
    profile.override_at = timezone.now() if classification else None
    profile.save()
    audit.record(
        action="risk.override.set" if classification else "risk.override.cleared",
        entity_type="User", entity_id=user.pk, actor=actor,
        before=before, after={"override": classification or None}, reason=reason, request=request,
    )
    return profile


def reassess_all(reason):
    from apps.accounts.models import User

    count = 0
    for user in User.objects.filter(role__in=[Role.BORROWER, Role.GUARANTOR], risk_profile__isnull=False).iterator():
        assess_risk(user, reason=reason)
        count += 1
    return count
