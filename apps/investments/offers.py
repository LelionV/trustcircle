"""
Open-offers marketplace: loans with no guarantor.

Investors see the borrower's trust score and risk class and offer an amount
and their own rate (within the admin's min/max). The offered money is held
in the investor's escrow while the offer is open. The borrower accepts
offers until the loan is full; each accepted offer becomes an Investment at
the offered rate. When the loan is full its rate becomes the amount-weighted
average of the accepted offers, the schedule is rebuilt from that rate, and
every other open offer is returned.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounting.models import AccountKind, EntryKind
from apps.audit import services as audit
from apps.commissions import calculators as fee_calc
from apps.commissions.services import rules
from apps.common.exceptions import BusinessRuleViolation
from apps.common.money import quantize_money
from apps.notifications.services import notify

from .models import Investment, InvestmentStatus, LoanOffer, OfferStatus


def _chat(loan, investor, kind, text, offer=None):
    from apps.chat.services import post_system

    post_system(loan=loan, members=[loan.borrower, investor], text=text, kind=kind, offer=offer)


def _release(offer, status, reason, actor=None):
    ledger.post(
        EntryKind.OFFER_RELEASE, f"Offer returned: {offer.loan.reference}",
        [ledger.Line(ledger.wallet(offer.investor, AccountKind.WALLET_ESCROW), "DEBIT", offer.amount, reason),
         ledger.Line(ledger.wallet(offer.investor), "CREDIT", offer.amount, reason)],
        loan=offer.loan, initiated_by=actor, idempotency_key=f"offer-release-{offer.pk}",
    )
    offer.status = status
    offer.decided_at = timezone.now()
    offer.save()


def _validate_rate(rate):
    o = rules()["offers"]
    rate = quantize_money(rate)
    if not Decimal(o["min_rate"]) <= rate <= Decimal(o["max_rate"]):
        raise BusinessRuleViolation(f"Offer a rate between {o['min_rate']}% and {o['max_rate']}%.",
                                    code="rate_out_of_range")
    return rate


@transaction.atomic
def make_offer(investor, loan_id, *, amount, rate, message="", request=None):
    from apps.investments.services import _lock_loan
    from apps.kyc.models import kyc_status_for
    from apps.loans.models import MARKETPLACE_STATUSES

    loan = _lock_loan(loan_id)
    amount = quantize_money(amount)
    rate = _validate_rate(rate)
    if loan.funding_mode != "OFFERS" or loan.status not in MARKETPLACE_STATUSES:
        raise BusinessRuleViolation("This loan isn't taking offers.", code="not_open")
    if loan.funding_expires_at and loan.funding_expires_at <= timezone.now():
        raise BusinessRuleViolation("The funding period for this loan has ended.", code="funding_expired")
    if kyc_status_for(investor) != "APPROVED":
        raise BusinessRuleViolation("Verify your identity (KYC) before making offers.", code="kyc_required")
    if loan.borrower_id == investor.pk:
        raise BusinessRuleViolation("You can't make an offer on your own loan.", code="own_loan")
    if LoanOffer.objects.filter(loan=loan, investor=investor, status=OfferStatus.OPEN).exists():
        raise BusinessRuleViolation("You already have an open offer on this loan. Change or withdraw it.",
                                    code="offer_exists")
    remaining = loan.amount - loan.funded_amount
    minimum = quantize_money(rules()["offers"]["min_amount"])
    if amount > remaining:
        raise BusinessRuleViolation(f"Only KES {remaining:,.2f} is still needed.", code="overfunding")
    if amount < minimum and amount != remaining:
        raise BusinessRuleViolation(f"The smallest offer is KES {minimum:,.2f} (or exactly what's left).",
                                    code="below_minimum")
    offer = LoanOffer(loan=loan, investor=investor, amount=amount, rate=rate, message=message[:500])
    offer.hold_entry = ledger.post(
        EntryKind.OFFER_HOLD, f"Offer on {loan.reference}",
        [ledger.Line(ledger.wallet(investor), "DEBIT", amount, f"Offer on {loan.reference}"),
         ledger.Line(ledger.wallet(investor, AccountKind.WALLET_ESCROW), "CREDIT", amount,
                     f"Held for offer on {loan.reference}")],
        loan=loan, initiated_by=investor,
    )
    offer.save()
    audit.record(action="offer.made", entity_type="LoanOffer", entity_id=offer.pk, actor=investor,
                 after={"loan": loan.reference, "amount": amount, "rate": rate}, request=request)
    _chat(loan, investor, "OFFER", f"Offer: KES {amount:,.2f} at {rate}%" + (f" — {message}" if message else ""),
          offer)
    notify(loan.borrower, "offer_received", "New offer on your loan",
           f"An investor offered KES {amount:,.2f} at {rate}% on {loan.reference}.", f"#/loans/{loan.pk}")
    return offer


@transaction.atomic
def change_offer(offer_id, investor, *, rate, message=None):
    offer = LoanOffer.objects.select_for_update().select_related("loan").get(pk=offer_id, investor=investor)
    if offer.status != OfferStatus.OPEN:
        raise BusinessRuleViolation("Only open offers can be changed.", code="not_open")
    old = offer.rate
    offer.rate = _validate_rate(rate)
    if message is not None:
        offer.message = message[:500]
    offer.save()
    _chat(offer.loan, investor, "OFFER", f"Offer changed: {old}% → {offer.rate}% on KES {offer.amount:,.2f}", offer)
    notify(offer.loan.borrower, "offer_changed", "An offer changed",
           f"An investor changed their offer on {offer.loan.reference} to {offer.rate}%.", f"#/loans/{offer.loan_id}")
    return offer


@transaction.atomic
def withdraw_offer(offer_id, investor):
    offer = LoanOffer.objects.select_for_update().select_related("loan").get(pk=offer_id, investor=investor)
    if offer.status != OfferStatus.OPEN:
        raise BusinessRuleViolation("This offer is no longer open.", code="not_open")
    _release(offer, OfferStatus.WITHDRAWN, "Offer withdrawn", actor=investor)
    _chat(offer.loan, investor, "SYSTEM", "The investor withdrew their offer.", offer)
    return offer


@transaction.atomic
def decline_offer(offer_id, borrower, reason=""):
    offer = LoanOffer.objects.select_for_update().select_related("loan", "investor").get(pk=offer_id)
    if offer.loan.borrower_id != borrower.pk:
        raise BusinessRuleViolation("This isn't your loan.", code="not_owner")
    if offer.status != OfferStatus.OPEN:
        raise BusinessRuleViolation("This offer is no longer open.", code="not_open")
    _release(offer, OfferStatus.DECLINED, "Offer declined by the borrower", actor=borrower)
    _chat(offer.loan, offer.investor, "SYSTEM", "The borrower declined this offer" + (f": {reason}" if reason else "."),
          offer)
    notify(offer.investor, "offer_declined", "Offer declined",
           f"Your offer on {offer.loan.reference} was declined. KES {offer.amount:,.2f} is back in your wallet.",
           "#/marketplace")
    return offer


@transaction.atomic
def accept_offer(offer_id, borrower, request=None):
    from apps.investments.services import _advance, _lock_loan, _move

    offer = LoanOffer.objects.select_for_update().select_related("investor").get(pk=offer_id)
    loan = _lock_loan(offer.loan_id)
    if loan.borrower_id != borrower.pk:
        raise BusinessRuleViolation("This isn't your loan.", code="not_owner")
    if offer.status != OfferStatus.OPEN or loan.status not in ("PUBLISHED", "PARTIALLY_FUNDED"):
        raise BusinessRuleViolation("This offer can't be accepted now.", code="not_open")
    remaining = loan.amount - loan.funded_amount
    if offer.amount > remaining:
        raise BusinessRuleViolation(
            f"This offer is for KES {offer.amount:,.2f} but only KES {remaining:,.2f} is still needed. "
            "Ask the investor (in chat) to offer a smaller amount.", code="overfunding")
    inv = Investment.objects.create(loan=loan, investor=offer.investor, amount=offer.amount, rate=offer.rate,
                                    status=InvestmentStatus.COMMITTED, commit_entry=offer.hold_entry)
    offer.status = OfferStatus.ACCEPTED
    offer.investment = inv
    offer.decided_at = timezone.now()
    offer.save()
    loan.funded_amount += offer.amount
    loan.save(update_fields=["funded_amount", "updated_at"])
    audit.record(action="offer.accepted", entity_type="LoanOffer", entity_id=offer.pk, actor=borrower,
                 after={"loan": loan.reference, "amount": offer.amount, "rate": offer.rate}, request=request)
    _chat(loan, offer.investor, "SYSTEM", f"Offer accepted: KES {offer.amount:,.2f} at {offer.rate}%.", offer)
    notify(offer.investor, "offer_accepted", "Your offer was accepted",
           f"The borrower accepted your offer of KES {offer.amount:,.2f} at {offer.rate}% on {loan.reference}.",
           "#/portfolio")
    if loan.funded_amount < loan.amount:
        if loan.status == "PUBLISHED":
            _move(loan, "PARTIALLY_FUNDED", actor=borrower, reason="First offer accepted")
        return offer

    # Full: fix the rate, rebuild the schedule, return everyone else's offers.
    _set_rate_from_offers(loan)
    _move(loan, "FULLY_FUNDED", actor=borrower, reason=f"Fully funded by offers at an average {loan.annual_rate}%")
    loan.fully_funded_at = timezone.now()
    loan.save(update_fields=["fully_funded_at", "updated_at"])
    for other in loan.offers.select_for_update().filter(status=OfferStatus.OPEN).select_related("investor"):
        _release(other, OfferStatus.EXPIRED, "The loan was filled by other offers")
        notify(other.investor, "offer_expired", "Loan filled",
               f"{loan.reference} was filled by other offers. KES {other.amount:,.2f} is back in your wallet.",
               "#/marketplace")
    _advance(loan)
    return offer


def _set_rate_from_offers(loan):
    from apps.loans import calculators as calc
    from apps.loans.models import LoanInstallment

    accepted = list(loan.investments.filter(status=InvestmentStatus.COMMITTED).values_list("amount", "rate"))
    loan.annual_rate = fee_calc.weighted_rate(accepted)
    loan.requires_manual_pricing = False
    schedule = calc.build_schedule(
        principal=loan.amount, annual_rate=loan.annual_rate, method=loan.interest_method, basis=loan.rate_basis,
        frequency=loan.repayment_frequency, term_months=loan.term_months, start_date=timezone.localdate(),
    )
    loan.installments.all().delete()
    LoanInstallment.objects.bulk_create([
        LoanInstallment(loan=loan, sequence=r["sequence"], due_date=r["due_date"], principal=r["principal"],
                        interest=r["interest"], fees=r["fees"], total=r["total"], balance_after=r["balance_after"])
        for r in schedule["installments"]
    ])
    loan.installment_count = schedule["installment_count"]
    loan.installment_amount = schedule["first_installment"]
    loan.total_interest = schedule["total_interest"]
    loan.total_repayable = schedule["total_repayable"]
    loan.save()


def release_open_offers(loan, reason):
    for offer in loan.offers.filter(status=OfferStatus.OPEN).select_related("investor", "loan"):
        _release(offer, OfferStatus.EXPIRED, reason)
        notify(offer.investor, "offer_expired", "Offer returned",
               f"Your offer on {loan.reference} was returned ({reason}). KES {offer.amount:,.2f} is back in your "
               "wallet.", "#/marketplace")
