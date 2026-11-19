from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from .models import KycStatus, KycSubmission, kyc_status_for


def _after_verification_change(user, reason):
    """Trust and risk depend on KYC; reassess both (imports avoid app cycles)."""
    from apps.risk_engine.services import assess_risk
    from apps.trust_engine.services import recalculate_trust

    recalculate_trust(user, reason=reason)
    assess_risk(user, reason=reason)


@transaction.atomic
def submit(user, data, request=None) -> KycSubmission:
    status = kyc_status_for(user)
    if status == KycStatus.PENDING:
        raise BusinessRuleViolation("Your documents are already waiting for review.", code="kyc_pending")
    if status == KycStatus.APPROVED:
        raise BusinessRuleViolation("Your identity is already verified.", code="kyc_approved")

    number = data["document_number"].strip().upper().replace(" ", "")
    if KycSubmission.objects.filter(
        document_type=data["document_type"], document_number=number, status=KycStatus.APPROVED
    ).exclude(user=user).exists():
        raise BusinessRuleViolation(
            "This document is already linked to another account. Contact support if this is a mistake.",
            code="document_in_use",
        )

    submission = KycSubmission.objects.create(user=user, **{**data, "document_number": number})
    audit.record(
        action="kyc.submitted",
        entity_type="KycSubmission",
        entity_id=submission.pk,
        actor=user,
        after={"document_type": submission.document_type, "user": str(user.pk)},
        request=request,
    )
    return submission


def _locked_pending(submission_id):
    submission = KycSubmission.objects.select_for_update().select_related("user").get(pk=submission_id)
    if submission.status != KycStatus.PENDING:
        raise BusinessRuleViolation("This submission has already been reviewed.", code="kyc_reviewed")
    return submission


@transaction.atomic
def approve(*, actor, submission_id, income_verified=False, note="", request=None) -> KycSubmission:
    submission = _locked_pending(submission_id)
    if submission.user_id == actor.pk:
        raise BusinessRuleViolation("You can't review your own documents.", code="self_review")
    now = timezone.now()
    submission.status = KycStatus.APPROVED
    submission.reviewed_by = actor
    submission.reviewed_at = now
    submission.review_note = note
    submission.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

    user = submission.user
    income_marked = False
    if income_verified and user.role in (Role.BORROWER, Role.GUARANTOR):
        from apps.accounts.profiles import get_profile

        profile = get_profile(user)
        if profile.monthly_income is None:
            raise BusinessRuleViolation(
                "The customer hasn't declared an income yet, so it can't be marked verified.",
                code="no_income_declared",
            )
        profile.income_verified = True
        profile.income_verified_at = now
        fields = ["income_verified", "income_verified_at", "updated_at"]
        if hasattr(profile, "income_verified_by"):
            profile.income_verified_by = actor
            fields.append("income_verified_by")
        profile.save(update_fields=fields)
        income_marked = True

    audit.record(
        action="kyc.approved",
        entity_type="KycSubmission",
        entity_id=submission.pk,
        actor=actor,
        before={"status": KycStatus.PENDING},
        after={"status": KycStatus.APPROVED, "income_verified": income_marked, "user": str(user.pk)},
        reason=note,
        request=request,
    )
    _after_verification_change(user, "Identity verified")
    return submission


@transaction.atomic
def reject(*, actor, submission_id, reason, request=None) -> KycSubmission:
    submission = _locked_pending(submission_id)
    if submission.user_id == actor.pk:
        raise BusinessRuleViolation("You can't review your own documents.", code="self_review")
    submission.status = KycStatus.REJECTED
    submission.reviewed_by = actor
    submission.reviewed_at = timezone.now()
    submission.rejection_reason = reason
    submission.save(update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason"])
    audit.record(
        action="kyc.rejected",
        entity_type="KycSubmission",
        entity_id=submission.pk,
        actor=actor,
        before={"status": KycStatus.PENDING},
        after={"status": KycStatus.REJECTED, "user": str(submission.user_id)},
        reason=reason,
        request=request,
    )
    return submission
