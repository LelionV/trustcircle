"""
Trust score services. Everything that changes a score goes through
`_apply`, which recalculates from the recorded facts, saves the score and
appends a TrustEvent with the reason. Scores are never edited directly.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from . import calculators as calc
from .models import (
    ExtensionRecord,
    LoanOutcome,
    ManualAdjustment,
    RepaymentRecord,
    TrustConfig,
    TrustEvent,
    TrustEventType,
    TrustScore,
)


def active_config():
    return TrustConfig.active(calc.default_parameters)


def _inputs(user):
    from apps.accounts.profiles import get_profile
    from apps.kyc.models import KycStatus, kyc_status_for

    profile = get_profile(user)
    records = list(RepaymentRecord.objects.filter(user=user, counted=True).values_list("counted_points", "days_early"))
    outcomes = LoanOutcome.objects.filter(user=user)
    return calc.TrustInputs(
        kyc_approved=kyc_status_for(user) == KycStatus.APPROVED,
        email_verified=user.is_email_verified,
        phone_verified=user.is_phone_verified,
        monthly_income=getattr(profile, "monthly_income", None),
        monthly_obligations=getattr(profile, "monthly_obligations", Decimal("0")) or Decimal("0"),
        income_verified=getattr(profile, "income_verified", False),
        account_age_days=max(0, (timezone.now() - user.date_joined).days),
        installments=[(points, days >= 0) for points, days in records],
        early_payments=sum(1 for _, d in records if d > 0),
        on_time_payments=sum(1 for _, d in records if d == 0),
        late_payments=sum(1 for _, d in records if d < 0),
        completed_loans=outcomes.filter(outcome=LoanOutcome.Outcome.COMPLETED).count(),
        defaults=outcomes.filter(outcome=LoanOutcome.Outcome.DEFAULTED).count(),
        extension_points=ExtensionRecord.objects.filter(user=user).aggregate(t=Sum("penalty_points"))["t"] or 0,
        manual_points=ManualAdjustment.objects.filter(user=user).aggregate(t=Sum("points"))["t"] or 0,
        early_completion_points=outcomes.aggregate(t=Sum("bonus_points"))["t"] or 0,
    )


def _apply(user, *, event_type, reason, points=None, reference="", actor=None, force_event=False):
    config = active_config()
    params = config.parameters
    inputs = _inputs(user)
    result = calc.calculate(inputs, params)

    score, _ = TrustScore.objects.select_for_update().get_or_create(user=user)
    before = score.score
    if before != result["score"]:
        score.previous_score = before
    score.score = result["score"]
    score.confidence = result["confidence"]
    score.breakdown = {
        "components": result["components"],
        "adjustments": result["adjustments"],
        "weighted": result["weighted"],
        "blend": result["blend"],
        "initial_score": params["initial_score"],
    }
    score.installments_counted = len(inputs.installments)
    score.early_payments = inputs.early_payments
    score.on_time_payments = inputs.on_time_payments
    score.late_payments = inputs.late_payments
    score.completed_loans = inputs.completed_loans
    score.defaults = inputs.defaults
    score.config = config
    score.last_assessed_at = timezone.now()
    score.save()

    if force_event or before != result["score"]:
        TrustEvent.objects.create(
            user=user, event_type=event_type, points=points, score_before=before, score_after=result["score"],
            reason=reason[:255], reference=reference, config=config, created_by=actor,
        )
    return score


@transaction.atomic
def recalculate_trust(user, reason="Score reassessed"):
    """Recalculate after verification or profile changes. Only borrowers have trust scores."""
    if user.role != Role.BORROWER:
        return None
    return _apply(user, event_type=TrustEventType.ASSESSMENT, reason=reason)


@transaction.atomic
def record_installment_payment(*, user, loan_reference, installment_reference, due_date, paid_on,
                               amount_due, amount_paid):
    """
    Called by the repayment engine when a scheduled installment is fully
    cleared. Idempotent: the same installment can never count twice.
    """
    existing = RepaymentRecord.objects.filter(installment_reference=installment_reference).first()
    if existing:
        return existing
    params = active_config().parameters
    used = RepaymentRecord.objects.filter(
        user=user, loan_reference=loan_reference, counted=True, counted_points__gt=0
    ).aggregate(t=Sum("counted_points"))["t"] or 0
    days_early = (due_date - paid_on).days
    counted, raw, counted_points, note = calc.installment_points(
        days_early=days_early, amount_paid=amount_paid, amount_due=amount_due,
        positive_points_used_on_loan=used, params=params,
    )
    record = RepaymentRecord.objects.create(
        user=user, loan_reference=loan_reference, installment_reference=installment_reference,
        due_date=due_date, paid_on=paid_on, amount_due=amount_due, amount_paid=amount_paid,
        days_early=days_early, counted=counted, raw_points=raw, counted_points=counted_points, note=note,
    )
    if days_early > 0:
        when = f"{days_early} day{'s' * (days_early != 1)} early"
    elif days_early == 0:
        when = "on the due date"
    else:
        when = f"{-days_early} day{'s' * (days_early != -1)} late"
    reason = f"Installment paid {when}" + (f" ({note})" if note else "")
    _apply(user, event_type=TrustEventType.INSTALLMENT_PAID, reason=reason,
           points=counted_points if counted else 0, reference=installment_reference, force_event=True)
    return record


@transaction.atomic
def record_loan_outcome(*, user, loan_reference, outcome, days_early=0):
    params = active_config().parameters
    bonus = 0
    rule = params.get("early_completion_bonus", calc.DEFAULT_PARAMETERS["early_completion_bonus"])
    if outcome == LoanOutcome.Outcome.COMPLETED and days_early >= rule["min_days_early"]:
        bonus = rule["points"]
    record, created = LoanOutcome.objects.get_or_create(
        loan_reference=loan_reference,
        defaults={"user": user, "outcome": outcome, "days_early": max(0, days_early), "bonus_points": bonus},
    )
    if created:
        completed = outcome == LoanOutcome.Outcome.COMPLETED
        when = f", {days_early} days early (+{bonus} bonus)" if bonus else ""
        _apply(
            user,
            event_type=TrustEventType.LOAN_COMPLETED if completed else TrustEventType.DEFAULT,
            reason=f"Loan {loan_reference} {'repaid in full' + when if completed else 'defaulted'}",
            points=(bonus or None) if completed else -params["default_penalty"],
            reference=loan_reference,
            force_event=True,
        )
    return record


@transaction.atomic
def record_extension(*, user, loan_reference, extension_reference, after_missed_payment):
    """An approved extension. It is not a default, but repeated or late requests cost points."""
    existing = ExtensionRecord.objects.filter(extension_reference=extension_reference).first()
    if existing:
        return existing
    rules = active_config().parameters["extension_penalties"]
    earlier = ExtensionRecord.objects.filter(user=user, loan_reference=loan_reference).count()
    penalty = rules["after_missed"] if after_missed_payment else rules["before_due"]
    penalty += rules["repeat_extra"] * earlier
    record = ExtensionRecord.objects.create(
        user=user, loan_reference=loan_reference, extension_reference=extension_reference,
        after_missed_payment=after_missed_payment, penalty_points=penalty,
    )
    what = "after a missed payment" if after_missed_payment else "before the due date"
    _apply(user, event_type=TrustEventType.EXTENSION, reason=f"Extension approved {what}",
           points=-penalty, reference=extension_reference, force_event=True)
    return record


@transaction.atomic
def manual_adjust(*, actor, user, points, reason, request=None):
    if user.role != Role.BORROWER:
        raise BusinessRuleViolation("Only borrowers have trust scores.", code="not_borrower")
    if user.pk == actor.pk:
        raise BusinessRuleViolation("You can't adjust your own score.", code="self_action")
    limit = active_config().parameters["manual_adjustment_limit"]
    if points == 0 or abs(points) > limit:
        raise BusinessRuleViolation(f"Adjust by between 1 and {limit} points, up or down.", code="bad_points")
    current = TrustScore.objects.filter(user=user).values_list("score", flat=True).first()
    if current is None:
        raise BusinessRuleViolation("This borrower has no score yet (identity not verified).", code="not_scored")
    ManualAdjustment.objects.create(user=user, points=points, reason=reason, created_by=actor)
    score = _apply(user, event_type=TrustEventType.MANUAL_ADJUSTMENT, reason=f"Adjusted by an administrator: {reason}",
                   points=points, actor=actor, force_event=True)
    audit.record(action="trust.adjusted", entity_type="User", entity_id=user.pk, actor=actor,
                 before={"score": current}, after={"score": score.score, "points": points},
                 reason=reason, request=request)
    return score


def recalculate_all(reason, actor=None):
    """After a rules change: reassess every borrower that has a score record."""
    from apps.accounts.models import User

    count = 0
    for user in User.objects.filter(role=Role.BORROWER, trust_score__isnull=False).iterator():
        with transaction.atomic():
            _apply(user, event_type=TrustEventType.RULES_CHANGED, reason=reason, actor=actor)
        count += 1
    return count
