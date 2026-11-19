"""
Loan applications: products, quotes, eligibility and the review workflow.

All amounts, rates and schedules are calculated here on the server; the
client only sends what the borrower asked for.
"""
import secrets
import string
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from . import calculators as calc
from .defaults import DEFAULT_PRODUCT
from .models import (
    IN_REVIEW_STATUSES,
    OPEN_LOAN_STATUSES,
    Loan,
    LoanInstallment,
    LoanProduct,
    LoanStatus,
    LoanStatusChange,
)
from .pricing import rate_for_score

ALLOWED_TRANSITIONS = {
    LoanStatus.DRAFT: {LoanStatus.SUBMITTED, LoanStatus.CANCELLED},
    LoanStatus.SUBMITTED: {LoanStatus.UNDER_REVIEW, LoanStatus.CANCELLED, LoanStatus.REJECTED, LoanStatus.APPROVED},
    LoanStatus.UNDER_REVIEW: {LoanStatus.APPROVED, LoanStatus.REJECTED, LoanStatus.CANCELLED},
    LoanStatus.APPROVED: {LoanStatus.PUBLISHED, LoanStatus.CANCELLED},
    LoanStatus.PUBLISHED: {LoanStatus.PARTIALLY_FUNDED, LoanStatus.FULLY_FUNDED, LoanStatus.CANCELLED},
    LoanStatus.PARTIALLY_FUNDED: {LoanStatus.PUBLISHED, LoanStatus.FULLY_FUNDED, LoanStatus.CANCELLED},
    LoanStatus.FULLY_FUNDED: {LoanStatus.GUARANTOR_PENDING, LoanStatus.READY_FOR_DISBURSEMENT,
                              LoanStatus.CANCELLED},
    LoanStatus.GUARANTOR_PENDING: {LoanStatus.READY_FOR_DISBURSEMENT, LoanStatus.CANCELLED},
    LoanStatus.READY_FOR_DISBURSEMENT: {LoanStatus.DISBURSED, LoanStatus.GUARANTOR_PENDING, LoanStatus.CANCELLED},
    LoanStatus.DISBURSED: {LoanStatus.ACTIVE},
    LoanStatus.ACTIVE: {LoanStatus.OVERDUE, LoanStatus.COMPLETED, LoanStatus.DEFAULTED},
    LoanStatus.OVERDUE: {LoanStatus.ACTIVE, LoanStatus.COMPLETED, LoanStatus.DEFAULTED},
    LoanStatus.DEFAULTED: {LoanStatus.COMPLETED},
}

# Loans that still need funding, a guarantor or the borrower's signature (can be cancelled with refunds).
PRE_DISBURSEMENT_STATUSES = (
    LoanStatus.PUBLISHED, LoanStatus.PARTIALLY_FUNDED, LoanStatus.FULLY_FUNDED, LoanStatus.GUARANTOR_PENDING,
    LoanStatus.READY_FOR_DISBURSEMENT,
)


def default_product():
    product = LoanProduct.objects.filter(is_active=True).first()
    if product is None and not LoanProduct.objects.exists():
        product = LoanProduct.objects.create(**DEFAULT_PRODUCT)
    return product


def _new_reference():
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    while True:
        ref = f"LN-{timezone.localdate():%y%m}-{''.join(secrets.choice(alphabet) for _ in range(6))}"
        if not Loan.objects.filter(reference=ref).exists():
            return ref


def _transition(loan, to_status, *, actor=None, reason="", request=None):
    if to_status not in ALLOWED_TRANSITIONS.get(loan.status, set()):
        raise BusinessRuleViolation(
            f"A loan that is '{loan.get_status_display().lower()}' can't move to "
            f"'{LoanStatus(to_status).label.lower()}'.",
            code="invalid_transition",
        )
    from_status = loan.status
    loan.status = to_status
    loan.save()
    LoanStatusChange.objects.create(loan=loan, from_status=from_status, to_status=to_status, actor=actor,
                                    reason=reason)
    audit.record(action=f"loan.{to_status.lower()}", entity_type="Loan", entity_id=loan.pk, actor=actor,
                 before={"status": from_status}, after={"status": to_status, "reference": loan.reference},
                 reason=reason, request=request)


def _lock(loan_id):
    return Loan.objects.select_for_update().select_related("product", "borrower").get(pk=loan_id)


# --- Eligibility and quotes ----------------------------------------------------------

def _problem(code, message, blocking=True):
    return {"code": code, "message": message, "blocking": blocking}


def eligibility(user, *, product, amount, term_months, frequency, monthly_income, monthly_obligations,
                schedule=None, guarantor=None, exclude_loan=None, for_submission=False):
    """Every reason the application can't go ahead (blocking) or needs attention (not blocking)."""
    from apps.kyc.models import KycStatus, kyc_status_for

    problems = []
    if user.is_frozen:
        problems.append(_problem("account_frozen", "Your account is frozen, so you can't apply right now."))
    kyc = kyc_status_for(user)
    if kyc != KycStatus.APPROVED:
        message = {
            KycStatus.PENDING: "Your identity documents are still being reviewed.",
            KycStatus.REJECTED: "Your identity documents were rejected. Submit them again from Identity verification.",
        }.get(kyc, "Verify your identity before applying.")
        problems.append(_problem("kyc_required", message))
    if not user.is_email_verified:
        problems.append(_problem("email_unverified", "Verify your email address."))
    if not user.is_phone_verified:
        problems.append(_problem("phone_unverified", "Verify your phone number."))

    if not product.is_active:
        problems.append(_problem("product_inactive", "This loan product isn't available any more."))
    if not product.min_amount <= amount <= product.max_amount:
        problems.append(_problem(
            "amount_out_of_range",
            f"Borrow between KES {product.min_amount:,.0f} and KES {product.max_amount:,.0f}."))
    if not product.min_term_months <= term_months <= product.max_term_months:
        problems.append(_problem(
            "term_out_of_range",
            f"Choose a repayment period of {product.min_term_months}–{product.max_term_months} months."))
    if frequency not in product.frequencies:
        problems.append(_problem("frequency_not_allowed", "That repayment frequency isn't offered for this loan."))

    if monthly_income is None:
        problems.append(_problem("income_missing", "Tell us your monthly income."))
    elif schedule is not None:
        disposable = Decimal(monthly_income) - Decimal(monthly_obligations or 0)
        limit = (disposable * product.max_installment_share / 100).quantize(Decimal("0.01"))
        if disposable <= 0:
            problems.append(_problem("no_disposable_income",
                                     "Your monthly commitments already use all of your income."))
        elif schedule["monthly_equivalent"] > limit:
            problems.append(_problem(
                "not_affordable",
                f"Repayments would be about KES {schedule['monthly_equivalent']:,.0f} a month, more than "
                f"{product.max_installment_share:.0f}% of what's left of your income after commitments "
                f"(KES {limit:,.0f}). Borrow less or choose a longer period."))

    others = Loan.objects.filter(borrower=user).exclude(pk=getattr(exclude_loan, "pk", None))
    if others.filter(status__in=IN_REVIEW_STATUSES).exists():
        problems.append(_problem("application_in_review", "You already have an application being reviewed."))
    if others.filter(status__in=OPEN_LOAN_STATUSES).count() >= product.max_open_loans:
        problems.append(_problem("open_loan_limit", "Finish your current loan before taking another."))

    if guarantor is None:
        # No guarantor: the loan goes to the open-offers marketplace, where investors propose their own rate.
        problems.append(_problem(
            "no_guarantor",
            "Without a guarantor your loan goes to the open-offers marketplace: investors see your trust score and "
            "offer their own monthly rate, and you choose which offers to accept.", blocking=False))
    return problems


def quote(user, *, product, amount, term_months, frequency, monthly_income=None, monthly_obligations=None,
          guarantor=None, exclude_loan=None, start_date=None):
    """What the loan would cost the borrower right now. Nothing is saved."""
    from apps.accounts.profiles import get_profile
    from apps.trust_engine.models import TrustScore

    profile = get_profile(user)
    if monthly_income is None:
        monthly_income = getattr(profile, "monthly_income", None)
    if monthly_obligations is None:
        monthly_obligations = getattr(profile, "monthly_obligations", Decimal("0")) or Decimal("0")

    trust = TrustScore.objects.filter(user=user).first()
    score = trust.score if trust else None
    bracket_set, bracket = rate_for_score(score)
    rate = bracket["annual_rate"] if bracket else None

    schedule = None
    if rate is not None:
        try:
            schedule = calc.build_schedule(
                principal=amount, annual_rate=rate, method=product.interest_method, basis=bracket_set.basis,
                frequency=frequency, term_months=term_months, start_date=start_date or timezone.localdate(),
            )
        except calc.ScheduleError as exc:
            raise BusinessRuleViolation(str(exc), code="invalid_terms") from exc

    problems = eligibility(
        user, product=product, amount=amount, term_months=term_months, frequency=frequency,
        monthly_income=monthly_income, monthly_obligations=monthly_obligations, schedule=schedule,
        guarantor=guarantor, exclude_loan=exclude_loan,
    )
    if score is not None and rate is None:
        problems.append(_problem("manual_pricing",
                                 "Your rate will be set by our credit team when they review the application.",
                                 blocking=False))
    return {
        "trust_score": score,
        "trust_confidence": trust.confidence if trust else "NEW",
        "bracket": bracket,
        "bracket_set_version": bracket_set.version,
        "annual_rate": rate,
        "rate_basis": bracket_set.basis,
        "funding_mode": "STANDARD" if guarantor else "OFFERS",
        "schedule": schedule,
        "problems": problems,
        "can_submit": not any(p["blocking"] for p in problems),
    }


# --- Borrower actions ---------------------------------------------------------------

def _guarantor_from_email(borrower, email):
    from apps.accounts.models import User

    if not email:
        return None
    guarantor = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if guarantor is None or guarantor.role != Role.GUARANTOR:
        raise BusinessRuleViolation("There's no guarantor account with that email. Ask them to sign up as a "
                                    "guarantor first.", code="guarantor_not_found")
    if guarantor.pk == borrower.pk:
        raise BusinessRuleViolation("You can't guarantee your own loan.", code="self_guarantee")
    if guarantor.is_frozen:
        raise BusinessRuleViolation("That guarantor can't take on guarantees right now.", code="guarantor_frozen")
    return guarantor


@transaction.atomic
def create_draft(user, data, request=None):
    if Loan.objects.filter(borrower=user, status=LoanStatus.DRAFT).exists():
        raise BusinessRuleViolation("You already have a draft application. Finish or cancel it first.",
                                    code="draft_exists")
    guarantor = _guarantor_from_email(user, data.pop("guarantor_email", ""))
    loan = Loan.objects.create(reference=_new_reference(), borrower=user, proposed_guarantor=guarantor, **data)
    LoanStatusChange.objects.create(loan=loan, to_status=LoanStatus.DRAFT, actor=user, reason="Application started")
    audit.record(action="loan.draft_created", entity_type="Loan", entity_id=loan.pk, actor=user,
                 after={"reference": loan.reference, "amount": loan.amount}, request=request)
    return loan


@transaction.atomic
def update_draft(loan_id, user, data):
    loan = _lock(loan_id)
    if loan.status != LoanStatus.DRAFT:
        raise BusinessRuleViolation("Only draft applications can be changed.", code="not_editable")
    if "guarantor_email" in data:
        loan.proposed_guarantor = _guarantor_from_email(user, data.pop("guarantor_email"))
    for key, value in data.items():
        setattr(loan, key, value)
    loan.save()
    return loan


def _snapshot_pricing(loan, *, manual_rate=None):
    """Copy trust, risk and the rate onto the loan and compute its totals."""
    from apps.risk_engine.services import assess_risk
    from apps.trust_engine.services import recalculate_trust

    trust = recalculate_trust(loan.borrower, reason=f"Assessed for loan {loan.reference}")
    risk = assess_risk(loan.borrower, reason=f"Assessed for loan {loan.reference}")
    bracket_set, bracket = rate_for_score(trust.score if trust else None)
    rate = bracket["annual_rate"] if bracket else None
    loan.trust_score_snapshot = trust.score if trust else None
    loan.trust_confidence_snapshot = trust.confidence if trust else ""
    loan.risk_score_snapshot = risk.score if risk else None
    loan.risk_class_snapshot = risk.effective_classification if risk else ""
    loan.bracket_set = bracket_set
    loan.bracket_label = bracket["label"] if bracket else ""
    loan.requires_manual_pricing = rate is None
    loan.annual_rate = manual_rate if (rate is None and manual_rate is not None) else rate
    loan.interest_method = loan.product.interest_method
    loan.rate_basis = bracket_set.basis  # the rate table decides how its rates are read
    schedule = None
    if loan.annual_rate is not None:
        schedule = calc.build_schedule(
            principal=loan.amount, annual_rate=loan.annual_rate, method=loan.interest_method,
            basis=loan.rate_basis, frequency=loan.repayment_frequency, term_months=loan.term_months,
            start_date=timezone.localdate(),
        )
        loan.installment_count = schedule["installment_count"]
        loan.installment_amount = schedule["first_installment"]
        loan.total_interest = schedule["total_interest"]
        loan.total_repayable = schedule["total_repayable"]
    return schedule


@transaction.atomic
def submit(loan_id, user, request=None):
    loan = _lock(loan_id)
    if loan.borrower_id != user.pk:
        raise BusinessRuleViolation("This isn't your application.", code="not_owner")
    from apps.accounts.profiles import get_profile, update_profile

    # Keep the profile in step with what the borrower declared on the application.
    profile = get_profile(user)
    declared = {"monthly_income": loan.monthly_income, "monthly_obligations": loan.monthly_obligations}
    if loan.employment_status:
        declared["employment_status"] = loan.employment_status
    if any(getattr(profile, k) != v for k, v in declared.items()):
        update_profile(user, {k: (str(v) if isinstance(v, Decimal) else v) for k, v in declared.items()},
                       request=request)

    schedule = _snapshot_pricing(loan)
    problems = eligibility(
        user, product=loan.product, amount=loan.amount, term_months=loan.term_months,
        frequency=loan.repayment_frequency, monthly_income=loan.monthly_income,
        monthly_obligations=loan.monthly_obligations, schedule=schedule, guarantor=loan.proposed_guarantor,
        exclude_loan=loan, for_submission=True,
    )
    blocking = [p for p in problems if p["blocking"]]
    if blocking:
        raise BusinessRuleViolation(blocking[0]["message"], code=blocking[0]["code"], extra={"problems": problems})
    loan.funding_mode = "STANDARD" if loan.proposed_guarantor_id else "OFFERS"
    loan.submitted_at = timezone.now()
    _transition(loan, LoanStatus.SUBMITTED, actor=user, reason="Submitted by borrower", request=request)
    if loan.proposed_guarantor_id:
        from apps.guarantors.services import ensure_request

        ensure_request(loan)  # the guarantor sees the request straight away
    return loan


@transaction.atomic
def cancel(loan_id, user, reason="", request=None):
    loan = _lock(loan_id)
    if loan.borrower_id != user.pk:
        raise BusinessRuleViolation("This isn't your application.", code="not_owner")
    if loan.status not in (LoanStatus.DRAFT, LoanStatus.SUBMITTED, LoanStatus.UNDER_REVIEW):
        raise BusinessRuleViolation("A loan that has been paid out can't be cancelled.",
                                    code="not_cancellable")
    loan.cancelled_at = timezone.now()
    _transition(loan, LoanStatus.CANCELLED, actor=user, reason=reason or "Cancelled by borrower", request=request)
    from apps.guarantors.services import release_for

    release_for(loan, "the application was cancelled")
    return loan


def cancel_any(loan_id, user, reason="", request=None):
    """Borrower cancels at any point before payout; investors get their money back."""
    loan = Loan.objects.get(pk=loan_id)
    if loan.borrower_id != user.pk:
        raise BusinessRuleViolation("This isn't your application.", code="not_owner")
    if loan.status in PRE_DISBURSEMENT_STATUSES or loan.status == LoanStatus.APPROVED:
        from apps.investments.services import cancel_funding

        return cancel_funding(loan.pk, actor=user, reason=reason or "Cancelled by borrower", request=request)
    return cancel(loan_id, user, reason, request)


# --- Administrator actions ------------------------------------------------------------

def _not_own(loan, actor):
    if loan.borrower_id == actor.pk:
        raise BusinessRuleViolation("You can't review your own loan.", code="self_review")


@transaction.atomic
def start_review(loan_id, actor, request=None):
    loan = _lock(loan_id)
    _not_own(loan, actor)
    if loan.status != LoanStatus.SUBMITTED:
        raise BusinessRuleViolation("Only submitted applications can be picked up for review.", code="not_submitted")
    loan.review_started_at = timezone.now()
    loan.reviewed_by = actor
    _transition(loan, LoanStatus.UNDER_REVIEW, actor=actor, reason="Review started", request=request)
    return loan


@transaction.atomic
def approve(loan_id, actor, reason, manual_rate=None, request=None):
    loan = _lock(loan_id)
    _not_own(loan, actor)
    if loan.status not in IN_REVIEW_STATUSES:
        raise BusinessRuleViolation("Only applications waiting for review can be approved.", code="not_in_review")
    previous_rate = loan.annual_rate
    schedule = _snapshot_pricing(loan, manual_rate=manual_rate)
    offers_mode = loan.funding_mode == "OFFERS"
    if loan.annual_rate is None and not offers_mode:
        raise BusinessRuleViolation("This borrower's bracket needs a manually set rate. Enter the rate.",
                                    code="manual_rate_required")
    if manual_rate is not None and not loan.requires_manual_pricing:
        raise BusinessRuleViolation("The rate comes from the borrower's bracket and can't be overridden here.",
                                    code="rate_not_manual")
    loan.installments.all().delete()
    if schedule:  # open-offers loans with no bracket rate get their schedule when the offers fill the loan
        LoanInstallment.objects.bulk_create([
            LoanInstallment(loan=loan, sequence=i["sequence"], due_date=i["due_date"], principal=i["principal"],
                            interest=i["interest"], fees=i["fees"], total=i["total"],
                            balance_after=i["balance_after"])
            for i in schedule["installments"]
        ])
    if offers_mode:
        loan.requires_manual_pricing = False  # investors set the rate with their offers
    now = timezone.now()
    loan.reviewed_by = actor
    loan.decided_at = now
    loan.decision_reason = reason
    loan.terms_locked_at = now
    note = reason
    if previous_rate is not None and previous_rate != loan.annual_rate:
        note = f"{reason} (rate updated from {previous_rate}% to {loan.annual_rate}% at approval)"
    _transition(loan, LoanStatus.APPROVED, actor=actor, reason=note, request=request)
    from apps.guarantors.services import adjust_locks_after_approval

    adjust_locks_after_approval(loan, actor=actor)
    return loan


@transaction.atomic
def reject(loan_id, actor, reason, request=None):
    loan = _lock(loan_id)
    _not_own(loan, actor)
    if loan.status not in IN_REVIEW_STATUSES:
        raise BusinessRuleViolation("Only applications waiting for review can be rejected.", code="not_in_review")
    loan.reviewed_by = actor
    loan.decided_at = timezone.now()
    loan.decision_reason = reason
    _transition(loan, LoanStatus.REJECTED, actor=actor, reason=reason, request=request)
    from apps.guarantors.services import release_for

    release_for(loan, "the application wasn't approved")
    return loan


@transaction.atomic
def publish(loan_id, actor, request=None):
    loan = _lock(loan_id)
    if loan.status != LoanStatus.APPROVED:
        raise BusinessRuleViolation("Only approved loans can be opened for funding.", code="not_approved")
    now = timezone.now()
    loan.published_at = now
    loan.funding_expires_at = now + timedelta(days=loan.product.funding_period_days)
    _transition(loan, LoanStatus.PUBLISHED, actor=actor,
                reason=f"Opened to investors until {timezone.localtime(loan.funding_expires_at):%d %b %Y}",
                request=request)
    from apps.notifications.services import notify

    if loan.proposed_guarantor_id:
        from apps.guarantors.services import ensure_request

        ensure_request(loan)  # normally already sent at submission; this covers older applications
    notify(loan.borrower, "loan_published", "Your loan is open for funding",
           f"{loan.reference} is now on the marketplace. Investors have until "
           f"{timezone.localtime(loan.funding_expires_at):%d %b %Y} to fund it.", f"#/loans/{loan.pk}")
    return loan


# --- Products ---------------------------------------------------------------------------

@transaction.atomic
def save_product(*, actor, data, product=None, request=None):
    before = None
    if product is None:
        product = LoanProduct(created_by=actor)
    else:
        before = {f: getattr(product, f) for f in data}
    for key, value in data.items():
        setattr(product, key, value)
    product.full_clean()
    product.save()
    audit.record(action="config.product.saved", entity_type="LoanProduct", entity_id=product.pk, actor=actor,
                 before=before, after=data, request=request)
    return product
