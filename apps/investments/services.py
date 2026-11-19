"""
Pooled funding (Phase 5) and disbursement (Phase 6).

invest()       investor commits money: available -> escrow, loan.funded_amount up.
cancel_funding refunds every commitment: escrow -> available.
disburse()     escrow of every investor -> borrower's available balance;
               the schedule is re-dated from the payout date (the rate and
               amounts stay as locked at approval).

Never overfunds: the loan row is locked, the remaining amount re-read, and a
database constraint (funded_amount <= amount) backs it up.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounting.models import AccountKind, EntryKind
from apps.audit import services as audit
from apps.commissions.services import rules
from apps.common.exceptions import BusinessRuleViolation
from apps.common.money import ZERO, quantize_money
from apps.notifications.services import notify, notify_admins

from .models import Investment, InvestmentStatus

GUARANTOR_GRACE_DAYS = 7  # after the funding deadline, before a loan still missing a guarantor is cancelled


def _lock_loan(loan_id):
    from apps.loans.models import Loan

    return Loan.objects.select_for_update().select_related("product", "borrower").get(pk=loan_id)


def _move(loan, to_status, actor=None, reason=""):
    from apps.loans.services import _transition

    _transition(loan, to_status, actor=actor, reason=reason)


# --- Investing -------------------------------------------------------------------------

@transaction.atomic
def invest(investor, loan_id, amount, *, idempotency_key="", request=None):
    from apps.kyc.models import kyc_status_for
    from apps.loans.models import MARKETPLACE_STATUSES

    if idempotency_key:
        existing = Investment.objects.filter(investor=investor, idempotency_key=idempotency_key).first()
        if existing:
            return existing
    loan = _lock_loan(loan_id)
    amount = quantize_money(amount)
    if kyc_status_for(investor) != "APPROVED":
        raise BusinessRuleViolation("Verify your identity (KYC) before investing.", code="kyc_required")
    if loan.status not in MARKETPLACE_STATUSES:
        raise BusinessRuleViolation("This loan isn't open for funding.", code="not_open")
    if loan.funding_mode == "OFFERS":
        raise BusinessRuleViolation("This loan has no guarantor: make an offer with your own rate instead.",
                                    code="offers_only")
    if loan.funding_expires_at and loan.funding_expires_at <= timezone.now():
        raise BusinessRuleViolation("The funding period for this loan has ended.", code="funding_expired")
    if loan.borrower_id == investor.pk:
        raise BusinessRuleViolation("You can't invest in your own loan.", code="own_loan")
    if loan.guarantees.filter(guarantor=investor, status__in=["REQUESTED", "ACCEPTED"]).exists():
        raise BusinessRuleViolation("You can't invest in a loan you guarantee.", code="conflict")
    remaining = loan.amount - loan.funded_amount
    minimum = quantize_money(rules()["limits"]["min_investment"])
    if amount <= 0:
        raise BusinessRuleViolation("Enter an amount.", code="invalid_amount")
    if amount > remaining:
        raise BusinessRuleViolation(f"Only KES {remaining:,.2f} is still needed.", code="overfunding",
                                    extra={"remaining": str(remaining)})
    if amount < minimum and amount != remaining:
        raise BusinessRuleViolation(f"The smallest investment is KES {minimum:,.2f} (or exactly what's left).",
                                    code="below_minimum")
    inv = Investment(loan=loan, investor=investor, amount=amount, rate=loan.annual_rate,
                     idempotency_key=idempotency_key)
    inv.commit_entry = ledger.post(
        EntryKind.INVESTMENT, f"Investment in {loan.reference}",
        [ledger.Line(ledger.wallet(investor), "DEBIT", amount, f"Invested in {loan.reference}"),
         ledger.Line(ledger.wallet(investor, AccountKind.WALLET_ESCROW), "CREDIT", amount,
                     f"Committed to {loan.reference}")],
        loan=loan, initiated_by=investor,
        idempotency_key=f"invest-{investor.pk}-{idempotency_key}" if idempotency_key else None,
    )
    inv.save()
    loan.funded_amount += amount
    loan.save(update_fields=["funded_amount", "updated_at"])
    audit.record(action="investment.created", entity_type="Investment", entity_id=inv.pk, actor=investor,
                 after={"loan": loan.reference, "amount": amount}, request=request)
    notify(investor, "investment_made", "Investment committed",
           f"KES {amount:,.2f} is committed to {loan.reference}. It stays in your wallet as 'committed' until the "
           "loan is fully funded and paid out.", "#/portfolio")
    if loan.funded_amount == loan.amount:
        _move(loan, "FULLY_FUNDED", reason="Fully funded")
        loan.fully_funded_at = timezone.now()
        loan.save(update_fields=["fully_funded_at", "updated_at"])
        notify(loan.borrower, "loan_funded", "Your loan is fully funded",
               f"Investors have funded all KES {loan.amount:,.2f} of {loan.reference}.", f"#/loans/{loan.pk}")
        _advance(loan)
    elif loan.status == "PUBLISHED":
        _move(loan, "PARTIALLY_FUNDED", reason="First investment received")
    return inv


@transaction.atomic
def withdraw_commitment(investment_id, investor, request=None):
    """An investor may take their money back while the loan is still filling up."""
    inv = Investment.objects.select_for_update().get(pk=investment_id, investor=investor)
    loan = _lock_loan(inv.loan_id)
    if inv.status != InvestmentStatus.COMMITTED or loan.status not in ("PUBLISHED", "PARTIALLY_FUNDED"):
        raise BusinessRuleViolation("This investment can no longer be withdrawn.", code="not_withdrawable")
    _refund(inv, "Withdrawn by investor", actor=investor)
    loan.funded_amount -= inv.amount
    loan.save(update_fields=["funded_amount", "updated_at"])
    if loan.funded_amount == 0 and loan.status == "PARTIALLY_FUNDED":
        _move(loan, "PUBLISHED", actor=investor, reason="All investments withdrawn")
    audit.record(action="investment.withdrawn", entity_type="Investment", entity_id=inv.pk, actor=investor,
                 request=request)
    return inv


def _refund(inv, reason, actor=None):
    ledger.post(
        EntryKind.INVESTMENT_RELEASE, f"Investment returned: {inv.loan.reference}",
        [ledger.Line(ledger.wallet(inv.investor, AccountKind.WALLET_ESCROW), "DEBIT", inv.amount, reason),
         ledger.Line(ledger.wallet(inv.investor), "CREDIT", inv.amount, reason)],
        loan=inv.loan, initiated_by=actor, idempotency_key=f"refund-{inv.pk}",
    )
    inv.status = InvestmentStatus.REFUNDED
    inv.save()
    notify(inv.investor, "investment_refunded", "Investment returned",
           f"KES {inv.amount:,.2f} committed to {inv.loan.reference} is back in your wallet ({reason}).", "#/wallet")


# --- After funding: guarantor and agreement --------------------------------------------------

def _advance(loan):
    """FULLY_FUNDED / GUARANTOR_PENDING -> READY_FOR_DISBURSEMENT when the guarantor (if needed) has accepted."""
    from apps.guarantors.services import guarantor_eligible
    from apps.loans import agreements

    needs_guarantor = loan.funding_mode != "OFFERS"
    if needs_guarantor and not guarantor_eligible(loan):
        if loan.status != "GUARANTOR_PENDING":
            _move(loan, "GUARANTOR_PENDING", reason="Waiting for the guarantor to accept")
        return
    _move(loan, "READY_FOR_DISBURSEMENT", reason="Funded and guaranteed; waiting for the borrower to sign")
    agreements.issue(loan)
    notify(loan.borrower, "agreement_ready", "Sign your loan agreement",
           f"{loan.reference} is ready. Read and accept the agreement so the money can be paid out.",
           f"#/loans/{loan.pk}")
    notify_admins("admin.loans.disburse", "loan_ready", "Loan ready to pay out",
                  f"{loan.reference} is funded and guaranteed.", "#/admin/disbursements")


@transaction.atomic
def after_guarantee_change(loan_id):
    from apps.guarantors.services import guarantor_eligible

    loan = _lock_loan(loan_id)
    if loan.status == "GUARANTOR_PENDING" and guarantor_eligible(loan):
        _advance(loan)
    elif loan.status == "READY_FOR_DISBURSEMENT" and not guarantor_eligible(loan) and loan.funding_mode != "OFFERS":
        _move(loan, "GUARANTOR_PENDING", reason="Guarantor withdrew")


# --- Cancelling and expiry --------------------------------------------------------------------

@transaction.atomic
def cancel_funding(loan_id, *, actor=None, reason, request=None):
    from apps.guarantors.services import release_for
    from apps.loans.services import PRE_DISBURSEMENT_STATUSES

    loan = _lock_loan(loan_id)
    if loan.status not in PRE_DISBURSEMENT_STATUSES and loan.status != "APPROVED":
        raise BusinessRuleViolation("This loan can't be cancelled now.", code="not_cancellable")
    for inv in loan.investments.filter(status=InvestmentStatus.COMMITTED).select_related("investor", "loan"):
        _refund(inv, reason, actor=actor)
    from .offers import release_open_offers

    release_open_offers(loan, reason)
    release_for(loan, "the loan was cancelled")
    loan.funded_amount = ZERO
    loan.cancelled_at = timezone.now()
    loan.save(update_fields=["funded_amount", "cancelled_at", "updated_at"])
    from apps.loans.services import _transition

    _transition(loan, "CANCELLED", actor=actor, reason=reason, request=request)
    if actor is None or actor.pk != loan.borrower_id:
        notify(loan.borrower, "loan_cancelled", "Loan cancelled", f"{loan.reference} was cancelled: {reason}.",
               f"#/loans/{loan.pk}")
    return loan


def expire_funding_rounds(now=None):
    """Scheduled: cancel loans whose funding period ran out (refunding investors)."""
    from apps.loans.models import Loan

    now = now or timezone.now()
    done = []
    for loan in Loan.objects.filter(status__in=["PUBLISHED", "PARTIALLY_FUNDED"], funding_expires_at__lte=now):
        cancel_funding(loan.pk, reason="The funding period ended before the loan was fully funded")
        done.append(loan.reference)
    cutoff = now - timedelta(days=GUARANTOR_GRACE_DAYS)
    for loan in Loan.objects.filter(status="GUARANTOR_PENDING", funding_expires_at__lte=cutoff):
        cancel_funding(loan.pk, reason="No guarantor accepted in time")
        done.append(loan.reference)
    return done


# --- Disbursement ----------------------------------------------------------------------------

@transaction.atomic
def disburse(loan_id, actor, request=None):
    from apps.loans import agreements
    from apps.loans import calculators as calc
    from apps.loans.models import LoanInstallment

    loan = _lock_loan(loan_id)
    if loan.borrower_id == actor.pk:
        raise BusinessRuleViolation("You can't pay out your own loan.", code="self_action")
    if loan.status != "READY_FOR_DISBURSEMENT":
        raise BusinessRuleViolation("This loan isn't ready to be paid out.", code="not_ready")
    agreement = agreements.current(loan)
    if agreement is None or agreement.accepted_at is None:
        raise BusinessRuleViolation("The borrower hasn't accepted the loan agreement yet.", code="agreement_pending")
    investments = list(loan.investments.select_for_update().filter(status=InvestmentStatus.COMMITTED)
                       .select_related("investor"))
    total = sum((i.amount for i in investments), ZERO)
    if total != loan.amount or loan.funded_amount != loan.amount:
        raise BusinessRuleViolation(f"Committed funds (KES {total:,.2f}) don't match the loan amount.",
                                    code="funding_mismatch")
    lines = [ledger.Line(ledger.wallet(i.investor, AccountKind.WALLET_ESCROW), "DEBIT", i.amount,
                         f"Lent via {loan.reference}") for i in investments]
    lines.append(ledger.Line(ledger.wallet(loan.borrower), "CREDIT", loan.amount, f"Loan {loan.reference} paid out"))
    ledger.post(EntryKind.DISBURSEMENT, f"Loan {loan.reference} paid out", lines, loan=loan, initiated_by=actor,
                idempotency_key=f"disburse-{loan.pk}")
    for i in investments:
        i.status = InvestmentStatus.ACTIVE
        i.save()

    # Re-date the schedule from today. Rate, method and amounts stay as locked at approval.
    schedule = calc.build_schedule(
        principal=loan.amount, annual_rate=loan.annual_rate, method=loan.interest_method, basis=loan.rate_basis,
        frequency=loan.repayment_frequency, term_months=loan.term_months, start_date=timezone.localdate(),
    )
    loan.installments.all().delete()
    LoanInstallment.objects.bulk_create([
        LoanInstallment(loan=loan, sequence=r["sequence"], due_date=r["due_date"], original_due_date=r["due_date"],
                        principal=r["principal"], interest=r["interest"], fees=r["fees"], total=r["total"],
                        balance_after=r["balance_after"])
        for r in schedule["installments"]
    ])
    loan.installment_amount = schedule["first_installment"]
    loan.total_interest = schedule["total_interest"]
    loan.total_repayable = schedule["total_repayable"]
    loan.disbursed_at = timezone.now()
    loan.disbursed_by = actor
    loan.save()
    _move(loan, "DISBURSED", actor=actor, reason=f"KES {loan.amount:,.2f} paid to the borrower's wallet")
    _move(loan, "ACTIVE", actor=actor, reason="Repayments start")
    audit.record(action="loan.disbursed_funds", entity_type="Loan", entity_id=loan.pk, actor=actor,
                 after={"amount": loan.amount, "investors": len(investments)}, request=request)
    first = schedule["installments"][0]
    notify(loan.borrower, "loan_disbursed", "Your loan has been paid out",
           f"KES {loan.amount:,.2f} is in your wallet. Your first payment of KES {first['total']:,.2f} is due on "
           f"{first['due_date']:%d %b %Y}.", f"#/loans/{loan.pk}")
    for i in investments:
        notify(i.investor, "investment_active", "Your investment is working",
               f"{loan.reference} has been paid out. You'll receive repayments as the borrower pays.", "#/portfolio")
    return loan


# --- Portfolio --------------------------------------------------------------------------------

def portfolio(investor):
    qs = Investment.objects.filter(investor=investor).select_related("loan")
    live = qs.filter(status__in=[InvestmentStatus.ACTIVE, InvestmentStatus.DEFAULTED])
    agg = qs.exclude(status=InvestmentStatus.REFUNDED).aggregate(
        invested=Sum("amount"), repaid=Sum("principal_repaid"), interest=Sum("interest_earned"),
        ext=Sum("extension_interest_earned"), recovered=Sum("recovered"))
    outstanding = sum((i.outstanding for i in live), ZERO)
    at_risk = sum((i.outstanding for i in live if i.loan.status in ("OVERDUE", "DEFAULTED")), ZERO)
    committed = qs.filter(status=InvestmentStatus.COMMITTED).aggregate(t=Sum("amount"))["t"] or ZERO
    earned = (agg["interest"] or ZERO) + (agg["ext"] or ZERO)
    invested = agg["invested"] or ZERO
    return {
        "total_invested": invested,
        "committed": committed,
        "outstanding_principal": outstanding,
        "principal_repaid": agg["repaid"] or ZERO,
        "recovered": agg["recovered"] or ZERO,
        "interest_earned": agg["interest"] or ZERO,
        "extension_interest_earned": agg["ext"] or ZERO,
        "total_earned": earned,
        "at_risk": at_risk,
        "return_percent": (earned * 100 / invested).quantize(Decimal("0.01")) if invested else ZERO,
        "counts": {s: qs.filter(status=s).count() for s in InvestmentStatus.values},
    }
