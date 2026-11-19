"""
Guarantees: requested when a loan opens for funding, accepted or declined by
the guarantor, replaced by the borrower if declined, released when the loan
is repaid or cancelled, and claimed if it defaults.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounting.models import AccountKind, EntryKind
from apps.accounts.models import Role, User
from apps.audit import services as audit
from apps.commissions.services import rules
from apps.common.exceptions import BusinessRuleViolation
from apps.notifications.services import notify

from .models import LIVE_GUARANTEE_STATUSES, Guarantee, GuaranteeStatus


def _max_multiple():
    """How much a guarantor may have guaranteed at once, as a multiple of declared monthly income."""
    return Decimal(str(rules()["guarantee"]["max_exposure_income_multiple"]))


def interest_to_lock(loan):
    """The borrower's total interest, which the guarantor must hold while guaranteeing."""
    if not rules()["guarantee"]["lock_interest"]:
        return Decimal("0.00")
    return loan.total_interest or Decimal("0.00")


def _move_lock(g, amount, *, lock, memo, actor=None):
    """Move `amount` between the guarantor's available and locked balances (callers hold the row lock)."""
    available = ledger.wallet(g.guarantor)
    locked = ledger.wallet(g.guarantor, AccountKind.WALLET_GUARANTEE_LOCK)
    src, dst = (available, locked) if lock else (locked, available)
    ledger.post(
        EntryKind.GUARANTEE_LOCK if lock else EntryKind.GUARANTEE_UNLOCK,
        f"{'Guarantee' if lock else 'Guarantee lock released'}: {g.loan.reference}",
        [ledger.Line(src, "DEBIT", amount, memo), ledger.Line(dst, "CREDIT", amount, memo)],
        loan=g.loan, initiated_by=actor,
    )


def lock_interest(g, actor=None):
    amount = interest_to_lock(g.loan)
    g.locked_amount = Decimal("0.00")
    g.lock_released_at = None
    if amount > 0:
        _move_lock(g, amount, lock=True, memo=f"Locked: guarantee for {g.loan.reference}", actor=actor)
        g.locked_amount = amount
    g.save(update_fields=["locked_amount", "lock_released_at", "updated_at"])


def release_lock(g, reason, actor=None):
    """Return a guarantee's locked interest to the guarantor's available balance (once)."""
    if g.locked_amount <= 0 or g.lock_released_at:
        return
    _move_lock(g, g.locked_amount, lock=False, memo=reason, actor=actor)
    g.lock_released_at = timezone.now()
    g.save(update_fields=["lock_released_at", "updated_at"])
    notify(g.guarantor, "guarantee_unlocked", "Guarantee money released",
           f"KES {g.locked_amount:,.2f} locked for {g.loan.reference} is available again ({reason}).", "#/wallet")


def live_guarantee(loan):
    return loan.guarantees.filter(status__in=LIVE_GUARANTEE_STATUSES).first()


def exposure(guarantor):
    from apps.loans.models import OPEN_LOAN_STATUSES

    return (Guarantee.objects.filter(guarantor=guarantor, status=GuaranteeStatus.ACCEPTED,
                                     loan__status__in=[*OPEN_LOAN_STATUSES, "SUBMITTED", "UNDER_REVIEW"])
            .aggregate(t=Sum("coverage_amount"))["t"] or Decimal("0"))


# Loan statuses in which a guarantor can be asked and can accept. Accepting before approval locks the interest
# as quoted; if approval changes it, adjust_locks_after_approval() locks or releases the difference.
REQUESTABLE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "PUBLISHED", "PARTIALLY_FUNDED", "FULLY_FUNDED",
                        "GUARANTOR_PENDING", "READY_FOR_DISBURSEMENT")
ACCEPTABLE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "PUBLISHED", "PARTIALLY_FUNDED", "FULLY_FUNDED",
                       "GUARANTOR_PENDING")


def can_accept(loan):
    return loan.status in ACCEPTABLE_STATUSES


def adjust_locks_after_approval(loan, actor=None):
    """
    Approval re-prices the loan. A guarantor who accepted earlier has the difference locked (if their
    wallet covers it) or released. If they can't cover an increase, the guarantee goes back to
    "waiting for a reply" with everything released, and they're asked to top up and accept again.
    """
    for g in loan.guarantees.select_for_update().filter(status=GuaranteeStatus.ACCEPTED).select_related("guarantor"):
        target = interest_to_lock(loan)
        diff = target - g.locked_amount
        if diff == 0:
            continue
        if diff < 0:
            _move_lock(g, -diff, lock=False, memo="Interest lower after approval", actor=actor)
            g.locked_amount = target
            g.save(update_fields=["locked_amount", "updated_at"])
        elif ledger.balances(g.guarantor)["available"] >= diff:
            _move_lock(g, diff, lock=True, memo="Interest higher after approval", actor=actor)
            g.locked_amount = target
            g.save(update_fields=["locked_amount", "updated_at"])
            notify(g.guarantor, "guarantee_lock_changed", "Guarantee lock updated",
                   f"{loan.reference} was approved with total interest KES {target:,.2f}; "
                   f"KES {diff:,.2f} more is now locked in your wallet.", "#/guarantees")
        else:
            release_lock(g, "the approved interest is higher than your available balance")
            g.status = GuaranteeStatus.REQUESTED
            g.responded_at = None
            g.save()
            notify(g.guarantor, "guarantee_requested", "Please accept the guarantee again",
                   f"{loan.reference} was approved with total interest KES {target:,.2f}, which is KES {diff:,.2f} "
                   "more than you locked. Top up your wallet and accept again.", "#/guarantees")


def request_guarantee(loan, guarantor):
    if live_guarantee(loan):
        raise BusinessRuleViolation("This loan already has a guarantor request open.", code="guarantee_exists")
    g = Guarantee.objects.create(loan=loan, guarantor=guarantor, coverage_amount=loan.amount)
    notify(guarantor, "guarantee_requested", "You've been asked to guarantee a loan",
           f"{loan.borrower.full_name} asked you to guarantee loan {loan.reference} for KES {loan.amount:,.2f}. "
           "Review it and accept or decline.", "#/guarantees")
    return g


def ensure_request(loan):
    """Send the named guarantor a request if they don't have one for this loan yet (never re-asks after a no)."""
    if not loan.proposed_guarantor_id or loan.funding_mode == "OFFERS" or loan.status not in REQUESTABLE_STATUSES:
        return None
    if live_guarantee(loan) or loan.guarantees.filter(guarantor_id=loan.proposed_guarantor_id).exists():
        return None
    return request_guarantee(loan, loan.proposed_guarantor)


def backfill_requests(guarantor):
    """Loans that name this guarantor but never sent a request (e.g. created before this version)."""
    from apps.loans.models import Loan

    for loan in Loan.objects.filter(proposed_guarantor=guarantor, status__in=REQUESTABLE_STATUSES) \
            .exclude(funding_mode="OFFERS").select_related("borrower"):
        with transaction.atomic():
            ensure_request(loan)


@transaction.atomic
def respond(guarantee_id, user, *, accept, note="", request=None):
    from apps.investments.services import after_guarantee_change
    from apps.kyc.models import kyc_status_for

    g = Guarantee.objects.select_for_update().select_related("loan", "loan__borrower").get(pk=guarantee_id,
                                                                                         guarantor=user)
    if g.status != GuaranteeStatus.REQUESTED:
        raise BusinessRuleViolation("You've already answered this request.", code="already_answered")
    if accept and not can_accept(g.loan):
        raise BusinessRuleViolation("This loan can no longer be guaranteed.", code="not_acceptable")
    if accept:
        if kyc_status_for(user) != "APPROVED":
            raise BusinessRuleViolation("Verify your identity (KYC) before guaranteeing a loan.", code="kyc_required")
        profile = getattr(user, "guarantor_profile", None)
        income = getattr(profile, "monthly_income", None)
        if not income:
            raise BusinessRuleViolation("Add your monthly income to your profile first.", code="profile_incomplete")
        limit = income * _max_multiple()
        if exposure(user) + g.coverage_amount > limit:
            raise BusinessRuleViolation(
                f"Guaranteeing this would take you over your limit of KES {limit:,.2f} "
                f"({_max_multiple():g}× monthly income).", code="exposure_limit")
        if g.loan.investments.filter(investor=user).exclude(status="REFUNDED").exists():
            raise BusinessRuleViolation("You've invested in this loan, so you can't also guarantee it.",
                                        code="conflict")
        need = interest_to_lock(g.loan)
        if ledger.balances(user)["available"] < need:
            raise BusinessRuleViolation(
                f"To guarantee this loan you need KES {need:,.2f} (the borrower's total interest) in your wallet. "
                "It's locked until the borrower has paid the interest, then released. Top up and try again.",
                code="insufficient_funds", extra={"required": str(need)})
    g.status = GuaranteeStatus.ACCEPTED if accept else GuaranteeStatus.DECLINED
    g.responded_at = timezone.now()
    g.response_note = note[:255]
    g.save()
    if accept:
        lock_interest(g, actor=user)
    audit.record(action=f"guarantee.{'accepted' if accept else 'declined'}", entity_type="Guarantee",
                 entity_id=g.pk, actor=user, after={"loan": g.loan.reference}, reason=note, request=request)
    loan = g.loan
    if accept:
        notify(loan.borrower, "guarantee_accepted", "Your guarantor accepted",
               f"{user.full_name} agreed to guarantee {loan.reference}.", f"#/loans/{loan.pk}")
    else:
        notify(loan.borrower, "guarantee_declined", "Your guarantor declined",
               f"{user.full_name} declined to guarantee {loan.reference}"
               f"{': ' + note if note else ''}. Nominate someone else to keep the loan going.", f"#/loans/{loan.pk}")
    after_guarantee_change(loan.pk)
    return g


@transaction.atomic
def withdraw(guarantee_id, user, note="", request=None):
    """A guarantor may change their mind until the money has been paid out."""
    from apps.investments.services import after_guarantee_change
    from apps.loans.services import PRE_DISBURSEMENT_STATUSES

    g = Guarantee.objects.select_for_update().select_related("loan").get(pk=guarantee_id, guarantor=user)
    if g.status != GuaranteeStatus.ACCEPTED or g.loan.status not in (*PRE_DISBURSEMENT_STATUSES, "APPROVED"):
        raise BusinessRuleViolation("This guarantee can't be withdrawn now.", code="not_withdrawable")
    g.status = GuaranteeStatus.WITHDRAWN
    g.response_note = note[:255]
    g.save()
    release_lock(g, "you withdrew the guarantee", actor=user)
    audit.record(action="guarantee.withdrawn", entity_type="Guarantee", entity_id=g.pk, actor=user, reason=note,
                 request=request)
    notify(g.loan.borrower, "guarantee_withdrawn", "Your guarantor withdrew",
           f"{user.full_name} withdrew their guarantee for {g.loan.reference}. Nominate someone else.",
           f"#/loans/{g.loan.pk}")
    after_guarantee_change(g.loan_id)
    return g


@transaction.atomic
def renominate(loan_id, borrower, email, request=None):
    from apps.loans.models import Loan

    loan = Loan.objects.select_for_update().get(pk=loan_id, borrower=borrower)
    if loan.status not in REQUESTABLE_STATUSES:
        raise BusinessRuleViolation("The guarantor can only be changed before the money is paid out.",
                                    code="not_changeable")
    if live_guarantee(loan):
        raise BusinessRuleViolation("Your current guarantor hasn't declined. Wait for their answer.",
                                    code="guarantee_exists")
    guarantor = User.objects.filter(email__iexact=email.strip(), is_active=True, role=Role.GUARANTOR).first()
    if guarantor is None:
        raise BusinessRuleViolation("There's no guarantor account with that email.", code="guarantor_not_found")
    if guarantor.pk == borrower.pk or guarantor.is_frozen:
        raise BusinessRuleViolation("That person can't guarantee this loan.", code="guarantor_invalid")
    if loan.investments.filter(investor=guarantor).exists():
        raise BusinessRuleViolation("An investor in this loan can't also guarantee it.", code="guarantor_invalid")
    loan.proposed_guarantor = guarantor
    if loan.status in ("SUBMITTED", "UNDER_REVIEW"):
        loan.funding_mode = "STANDARD"  # named a guarantor before approval: priced from the bracket table
    loan.save(update_fields=["proposed_guarantor", "funding_mode", "updated_at"])
    g = request_guarantee(loan, guarantor)
    audit.record(action="guarantee.renominated", entity_type="Loan", entity_id=loan.pk, actor=borrower,
                 after={"guarantor": guarantor.email}, request=request)
    return g


def release_for(loan, reason):
    for g in loan.guarantees.filter(status__in=LIVE_GUARANTEE_STATUSES).select_related("loan", "guarantor"):
        g.status = GuaranteeStatus.RELEASED
        g.response_note = reason[:255]
        g.save()
        release_lock(g, reason)
        notify(g.guarantor, "guarantee_released", "Guarantee released",
               f"You're no longer guaranteeing {loan.reference}: {reason}.", "#/guarantees")


def guarantor_eligible(loan):
    """Does the guarantor earn a commission on this loan's interest?"""
    return loan.guarantees.filter(status=GuaranteeStatus.ACCEPTED).exists()
