"""
Repayments (Phase 8).

repay()            borrower's wallet -> investors, guarantor and platform,
                   in one balanced journal entry. Allocation and distribution
                   come from the pure functions in .calculators.
process_overdue()  daily: due/overdue statuses, late fees, reminders, defaults.
default_loan()     marks the default, records it in the trust engine and calls
                   on the guarantor.
collect_claim()    takes what it can from the guarantor's wallet and returns it
                   to investors pro rata.
Extensions         request -> admin review -> investor consent (per rules) ->
                   schedule shifted, charges added, new agreement version.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounting.models import AccountKind, EntryKind
from apps.audit import services as audit
from apps.commissions import calculators as fees
from apps.commissions.services import rules
from apps.common.exceptions import BusinessRuleViolation
from apps.common.money import ZERO, quantize_money
from apps.notifications.services import notify, notify_admins

from . import calculators as calc
from .models import DistributionLine, ExtensionRequest, ExtensionStatus, ExtensionVote, Repayment, ShareRole

REPAYABLE_STATUSES = ("ACTIVE", "OVERDUE", "DEFAULTED")


def _lock_loan(loan_id):
    from apps.loans.models import Loan

    return Loan.objects.select_for_update().select_related("borrower", "product").get(pk=loan_id)


def _unpaid(loan, lock=True):
    from apps.loans.models import PAID_STATUSES

    qs = loan.installments.exclude(status__in=PAID_STATUSES).order_by("sequence")
    return list(qs.select_for_update() if lock else qs)


def _move(loan, status, actor=None, reason=""):
    from apps.loans.services import _transition

    _transition(loan, status, actor=actor, reason=reason)


def _live_investments(loan):
    from apps.investments.models import InvestmentStatus

    return list(loan.investments.select_for_update()
                .filter(status__in=[InvestmentStatus.ACTIVE, InvestmentStatus.DEFAULTED])
                .select_related("investor").order_by("created_at"))


def outstanding(loan):
    """What the borrower still owes, by component."""
    result = {c: ZERO for c in calc.COMPONENTS}
    for inst in _unpaid(loan, lock=False):
        for c in calc.COMPONENTS:
            result[c] += inst.due(c)
    result["total"] = sum((result[c] for c in calc.COMPONENTS), ZERO)
    return result


# --- Repaying ----------------------------------------------------------------------------

@transaction.atomic
def repay(loan_id, payer, amount, *, idempotency_key="", request=None):
    from apps.guarantors.models import GuaranteeStatus
    from apps.trust_engine.services import record_installment_payment

    loan = _lock_loan(loan_id)
    if idempotency_key:
        existing = Repayment.objects.filter(loan=loan, idempotency_key=idempotency_key).first()
        if existing:
            return existing
    if loan.borrower_id != payer.pk:
        raise BusinessRuleViolation("Only the borrower can repay this loan.", code="not_owner")
    if loan.status not in REPAYABLE_STATUSES:
        raise BusinessRuleViolation("This loan isn't being repaid.", code="not_repayable")
    amount = quantize_money(amount)
    installments = _unpaid(loan)
    try:
        alloc = calc.allocate_payment(amount, [
            {"id": i.pk, **{f"{c}_due": i.due(c) for c in calc.COMPONENTS}} for i in installments])
    except calc.AllocationError as exc:
        raise BusinessRuleViolation(str(exc), code="invalid_amount") from exc
    totals = alloc["totals"]

    investments = _live_investments(loan)
    owed_to_investors = sum((i.outstanding for i in investments), ZERO)
    principal_to_investors = min(totals["principal"], owed_to_investors)
    reimbursement = totals["principal"] - principal_to_investors  # guarantor already covered this principal
    guarantee = loan.guarantees.filter(status__in=[GuaranteeStatus.ACCEPTED, GuaranteeStatus.CLAIMED]) \
        .select_related("guarantor").first()
    claim = getattr(guarantee, "claim", None) if guarantee else None
    if reimbursement and claim is None:
        raise BusinessRuleViolation("Repayment is more than investors are owed.", code="invalid_amount")
    eligible = bool(guarantee and guarantee.status == GuaranteeStatus.ACCEPTED)
    r = rules()
    dist = calc.distribute(
        principal=principal_to_investors, interest=totals["interest"],
        extension_interest=totals["extension_interest"],
        investments=[(i.pk, i.outstanding, i.amount, i.rate) for i in investments], split=r["revenue_split"],
        guarantor_eligible=eligible,
    )

    lines = [ledger.Line(ledger.wallet(payer), "DEBIT", amount, f"Repayment of {loan.reference}")]
    for inv in investments:
        share = dist["investors"][inv.pk]
        lines.append(ledger.Line(ledger.wallet(inv.investor), "CREDIT", sum(share.values(), ZERO),
                                 f"Repayment from {loan.reference}"))
    g_share = dist["guarantor"]["interest"] + dist["guarantor"]["extension_interest"]
    if guarantee and (g_share or reimbursement):
        lines.append(ledger.Line(ledger.wallet(guarantee.guarantor), "CREDIT", g_share + reimbursement,
                                 f"Guarantor share from {loan.reference}"))
    lines += [
        ledger.Line(ledger.platform(AccountKind.REVENUE_INTEREST), "CREDIT", dist["platform"]["interest"],
                    "Interest commission"),
        ledger.Line(ledger.platform(AccountKind.REVENUE_EXTENSION_INTEREST), "CREDIT",
                    dist["platform"]["extension_interest"], "Extension interest"),
        ledger.Line(ledger.platform(AccountKind.REVENUE_EXTENSION_FEE), "CREDIT", totals["extension_fee"],
                    "Extension fee"),
        ledger.Line(ledger.platform(AccountKind.REVENUE_LATE_FEE), "CREDIT", totals["late_fee"], "Late fee"),
    ]
    entry = ledger.post(EntryKind.REPAYMENT, f"Repayment of {loan.reference}", lines, loan=loan, initiated_by=payer,
                        idempotency_key=f"repay-{loan.pk}-{idempotency_key}" if idempotency_key else None)

    # Installments
    today = timezone.localdate()
    by_id = {i.pk: i for i in installments}
    cleared = []
    for line in alloc["lines"]:
        inst = by_id[line["id"]]
        for c in calc.COMPONENTS:
            setattr(inst, f"{c}_paid", getattr(inst, f"{c}_paid") + line[c])
        inst.amount_paid = sum((getattr(inst, f"{c}_paid") for c in calc.COMPONENTS), ZERO)
        if line["cleared"]:
            inst.status = calc.installment_outcome(inst.due_date, today)
            inst.paid_at = timezone.now()
            cleared.append(inst)
        elif inst.status in ("UPCOMING", "DUE"):
            inst.status = "PARTIALLY_PAID"
        inst.save()

    repayment = Repayment.objects.create(
        loan=loan, payer=payer, amount=amount, principal=totals["principal"], interest=totals["interest"],
        extension_interest=totals["extension_interest"], extension_fee=totals["extension_fee"],
        late_fee=totals["late_fee"], entry=entry, idempotency_key=idempotency_key,
        allocation=[{"sequence": by_id[l["id"]].sequence, "cleared": l["cleared"],
                     **{c: str(l[c]) for c in calc.COMPONENTS}} for l in alloc["lines"]],
    )
    for inv in investments:
        share = dist["investors"][inv.pk]
        if not any(share.values()):
            continue
        inv.principal_repaid += share["principal"]
        inv.interest_earned += share["interest"]
        inv.extension_interest_earned += share["extension_interest"]
        inv.save()
        DistributionLine.objects.create(repayment=repayment, loan=loan, role=ShareRole.INVESTOR,
                                        recipient=inv.investor, investment=inv, entry=entry, **share)
    if guarantee and (g_share or reimbursement):
        guarantee.commission_earned += g_share
        guarantee.save()
        DistributionLine.objects.create(repayment=repayment, loan=loan, role=ShareRole.GUARANTOR,
                                        recipient=guarantee.guarantor, principal=reimbursement,
                                        interest=dist["guarantor"]["interest"],
                                        extension_interest=dist["guarantor"]["extension_interest"], entry=entry)
        if reimbursement:
            claim.reimbursed += reimbursement
            claim.save()
    DistributionLine.objects.create(
        repayment=repayment, loan=loan, role=ShareRole.PLATFORM, interest=dist["platform"]["interest"],
        extension_interest=dist["platform"]["extension_interest"],
        fees=totals["extension_fee"] + totals["late_fee"], entry=entry)

    for inst in cleared:
        record_installment_payment(
            user=loan.borrower, loan_reference=loan.reference,
            installment_reference=f"{loan.reference}-{inst.sequence}", due_date=inst.due_date, paid_on=today,
            amount_due=inst.amount_due, amount_paid=inst.amount_paid)

    audit.record(action="loan.repaid", entity_type="Loan", entity_id=loan.pk, actor=payer,
                 after={"amount": amount, "repayment": str(repayment.pk)}, request=request)
    notify(payer, "repayment_received", "Payment received",
           f"KES {amount:,.2f} was applied to {loan.reference}.", f"#/loans/{loan.pk}")
    for inv in investments:
        share = dist["investors"][inv.pk]
        total = sum(share.values(), ZERO)
        if total:
            notify(inv.investor, "distribution_received", "Repayment received",
                   f"KES {total:,.2f} from {loan.reference} is in your wallet "
                   f"(principal {share['principal']:,.2f}, interest "
                   f"{share['interest'] + share['extension_interest']:,.2f}).", "#/portfolio")
    _after_payment(loan)
    return repayment


def _after_payment(loan):
    from apps.guarantors.services import release_for, release_lock
    from apps.investments.models import InvestmentStatus
    from apps.trust_engine.services import record_loan_outcome

    remaining = _unpaid(loan)
    if remaining and all(i.interest_paid >= i.interest for i in loan.installments.all()):
        # The borrower has paid all the scheduled interest: free the guarantor's locked interest.
        for g in loan.guarantees.filter(status="ACCEPTED", locked_amount__gt=0, lock_released_at__isnull=True) \
                .select_related("loan", "guarantor"):
            release_lock(g, "the borrower has paid the interest in full")
    if not remaining:
        loan.completed_at = timezone.now()
        loan.overdue_since = None
        loan.save()
        _move(loan, "COMPLETED", reason="Repaid in full")
        loan.investments.filter(status__in=[InvestmentStatus.ACTIVE, InvestmentStatus.DEFAULTED]) \
            .update(status=InvestmentStatus.COMPLETED)
        release_for(loan, "the loan was repaid in full")
        last_due = loan.installments.order_by("-sequence").values_list("original_due_date", "due_date").first()
        final_due = (last_due[0] or last_due[1]) if last_due else None
        record_loan_outcome(user=loan.borrower, loan_reference=loan.reference, outcome="COMPLETED",
                            days_early=(final_due - timezone.localdate()).days if final_due else 0)
        notify(loan.borrower, "loan_completed", "Loan repaid in full",
               f"Well done: {loan.reference} is fully repaid. This counts towards your trust score.",
               f"#/loans/{loan.pk}")
        return
    if loan.status == "OVERDUE":
        grace = rules()["overdue"]["grace_days"]
        today = timezone.localdate()
        if not any(i.due_date + timedelta(days=grace) < today for i in remaining):
            loan.overdue_since = None
            loan.save()
            _move(loan, "ACTIVE", reason="Overdue payments cleared")


# --- Daily: due, overdue, late fees, reminders, defaults ------------------------------------

def process_overdue(today=None):
    from apps.loans.models import Loan

    today = today or timezone.localdate()
    o = rules()["overdue"]
    summary = {"reminders": 0, "late_fees": 0, "overdue_loans": 0, "defaults": 0}
    for loan_id in Loan.objects.filter(status__in=["ACTIVE", "OVERDUE"]).values_list("pk", flat=True):
        with transaction.atomic():
            loan = _lock_loan(loan_id)
            unpaid = _unpaid(loan)
            for inst in unpaid:
                days_to_due = (inst.due_date - today).days
                if days_to_due == o["reminder_days_before"]:
                    if notify(loan.borrower, "payment_reminder", "Payment due soon",
                              f"KES {inst.outstanding:,.2f} for {loan.reference} is due on {inst.due_date:%d %b %Y}.",
                              f"#/loans/{loan.pk}", dedupe_key=f"reminder-{inst.pk}-{inst.due_date}"):
                        summary["reminders"] += 1
                if days_to_due == 0 and inst.status == "UPCOMING":
                    inst.status = "DUE"
                    inst.save()
                if (today - inst.due_date).days > o["grace_days"] and inst.status not in ("OVERDUE", "DEFAULTED"):
                    inst.status = "OVERDUE"
                    if inst.late_fee == 0:
                        inst.late_fee = fees.late_fee(inst.principal + inst.interest, rules())
                        summary["late_fees"] += 1
                    inst.save()
                    notify(loan.borrower, "payment_overdue", "Payment overdue",
                           f"Your payment for {loan.reference} due {inst.due_date:%d %b %Y} is overdue. "
                           f"A late fee of KES {inst.late_fee:,.2f} has been added. Pay now to protect your "
                           "trust score.", f"#/loans/{loan.pk}", dedupe_key=f"overdue-{inst.pk}-{inst.due_date}")
            overdue = [i for i in unpaid if i.status in ("OVERDUE", "DEFAULTED")]
            if overdue and loan.status == "ACTIVE":
                loan.overdue_since = min(i.due_date for i in overdue)
                loan.save()
                _move(loan, "OVERDUE", reason="A payment is past its grace period")
                summary["overdue_loans"] += 1
                if loan.guarantees.filter(status="ACCEPTED").exists():
                    g = loan.guarantees.get(status="ACCEPTED")
                    notify(g.guarantor, "guaranteed_loan_overdue", "A loan you guarantee is overdue",
                           f"{loan.reference} has a missed payment. If it isn't caught up, you may be asked to "
                           "cover it.", "#/guarantees", dedupe_key=f"g-overdue-{loan.pk}-{loan.overdue_since}")
            if overdue and (today - min(i.due_date for i in overdue)).days > o["default_after_days"]:
                default_loan(loan, reason=f"A payment is more than {o['default_after_days']} days overdue")
                summary["defaults"] += 1
    return summary


def default_loan(loan, *, reason, actor=None):
    from apps.guarantors.models import GuaranteeClaim, GuaranteeStatus
    from apps.investments.models import InvestmentStatus
    from apps.trust_engine.services import record_loan_outcome

    loan.defaulted_at = timezone.now()
    loan.save()
    _move(loan, "DEFAULTED", actor=actor, reason=reason)
    for inst in _unpaid(loan):
        inst.status = "DEFAULTED"
        inst.save()
    investments = _live_investments(loan)
    for inv in investments:
        inv.status = InvestmentStatus.DEFAULTED
        inv.save()
        notify(inv.investor, "loan_defaulted", "A loan you funded has defaulted",
               f"{loan.reference} is in default. Any guarantor recovery and later payments will be returned to "
               f"you in proportion to the KES {inv.outstanding:,.2f} you're still owed.", "#/portfolio")
    record_loan_outcome(user=loan.borrower, loan_reference=loan.reference, outcome="DEFAULTED")
    notify(loan.borrower, "loan_defaulted", "Your loan is in default",
           f"{loan.reference} is in default ({reason}). Contact support to agree a way forward.",
           f"#/loans/{loan.pk}")
    notify_admins("admin.defaults.manage", "loan_defaulted", "Loan defaulted", f"{loan.reference}: {reason}",
                  "#/admin/defaults")
    guarantee = loan.guarantees.filter(status=GuaranteeStatus.ACCEPTED).select_related("guarantor", "loan").first()
    if guarantee:
        from apps.guarantors.services import release_lock

        # The locked interest is freed into the guarantor's wallet and used first for the claim below.
        release_lock(guarantee, "used towards the guarantee claim")
        owed = sum((i.outstanding for i in investments), ZERO)
        guarantee.status = GuaranteeStatus.CLAIMED
        guarantee.save()
        claim = GuaranteeClaim.objects.create(guarantee=guarantee, amount=min(owed, guarantee.coverage_amount))
        notify(guarantee.guarantor, "guarantee_claimed", "Your guarantee has been called on",
               f"{loan.reference} defaulted. You guaranteed it, so KES {claim.amount:,.2f} is owed to its investors. "
               "Money in your wallet will be used towards it; top up to settle the rest.", "#/guarantees")
        collect_claim(claim.pk)
    audit.record(action="loan.defaulted", entity_type="Loan", entity_id=loan.pk, actor=actor, reason=reason)


@transaction.atomic
def collect_claim(claim_id, actor=None, amount=None, request=None):
    """Take up to `amount` (default: whatever is available) from the guarantor towards the claim."""
    from apps.guarantors.models import ClaimStatus, GuaranteeClaim

    claim = GuaranteeClaim.objects.select_for_update().select_related("guarantee__guarantor", "guarantee__loan") \
        .get(pk=claim_id)
    if claim.status in (ClaimStatus.RECOVERED, ClaimStatus.WRITTEN_OFF):
        return claim
    guarantor, loan = claim.guarantee.guarantor, claim.guarantee.loan
    available = ledger.balances(guarantor)["available"]
    take = min(available, claim.outstanding, quantize_money(amount) if amount else claim.outstanding)
    investments = _live_investments(loan)
    owed = [(i.pk, i.outstanding) for i in investments]
    take = min(take, sum((o for _, o in owed), ZERO))
    if take <= 0:
        return claim
    parts = calc.split_recovery(take, owed)
    lines = [ledger.Line(ledger.wallet(guarantor), "DEBIT", take, f"Guarantee for {loan.reference}")]
    lines += [ledger.Line(ledger.wallet(i.investor), "CREDIT", parts[i.pk], f"Recovered from {loan.reference}")
              for i in investments if parts[i.pk]]
    entry = ledger.post(EntryKind.RECOVERY, f"Guarantor recovery for {loan.reference}", lines, loan=loan,
                        initiated_by=actor)
    for inv in investments:
        if parts[inv.pk]:
            inv.recovered += parts[inv.pk]
            inv.save()
            DistributionLine.objects.create(loan=loan, role=ShareRole.INVESTOR, recipient=inv.investor,
                                            investment=inv, principal=parts[inv.pk], is_recovery=True, entry=entry)
            notify(inv.investor, "recovery_received", "Money recovered",
                   f"KES {parts[inv.pk]:,.2f} was recovered from the guarantor of {loan.reference}.", "#/portfolio")
    claim.recovered += take
    claim.status = ClaimStatus.RECOVERED if claim.recovered >= claim.amount else ClaimStatus.PARTLY_RECOVERED
    claim.save()
    notify(guarantor, "guarantee_payment", "Guarantee payment taken",
           f"KES {take:,.2f} was taken from your wallet for {loan.reference}. "
           f"Still owed: KES {claim.outstanding:,.2f}.", "#/guarantees")
    audit.record(action="guarantee.recovered", entity_type="GuaranteeClaim", entity_id=claim.pk, actor=actor,
                 after={"amount": take}, request=request)
    return claim


def collect_open_claims():
    from apps.guarantors.models import ClaimStatus, GuaranteeClaim

    n = 0
    for claim_id in GuaranteeClaim.objects.filter(status__in=[ClaimStatus.OPEN, ClaimStatus.PARTLY_RECOVERED]) \
            .values_list("pk", flat=True):
        before = GuaranteeClaim.objects.get(pk=claim_id).recovered
        if collect_claim(claim_id).recovered > before:
            n += 1
    return n


@transaction.atomic
def write_off_claim(claim_id, actor, reason, request=None):
    from apps.guarantors.models import ClaimStatus, GuaranteeClaim

    claim = GuaranteeClaim.objects.select_for_update().get(pk=claim_id)
    claim.status = ClaimStatus.WRITTEN_OFF
    claim.note = reason
    claim.save()
    audit.record(action="guarantee.claim_written_off", entity_type="GuaranteeClaim", entity_id=claim.pk,
                 actor=actor, reason=reason, request=request)
    return claim


# --- Extensions ------------------------------------------------------------------------------

def quote_extension(loan, days):
    e = rules()["extension"]
    principal = sum((i.principal - i.principal_paid for i in _unpaid(loan, lock=False)), ZERO)
    charges = fees.extension_charges(principal, days, rules())
    problems = []
    if loan.status not in ("ACTIVE", "OVERDUE"):
        problems.append("Only loans being repaid can be extended.")
    if loan.extension_count >= e["max_extensions_per_loan"]:
        problems.append(f"This loan has had the maximum of {e['max_extensions_per_loan']} extensions.")
    if not 1 <= days <= e["max_extension_days"]:
        problems.append(f"An extension can be 1 to {e['max_extension_days']} days.")
    if loan.status == "OVERDUE" and not e["allow_after_due_date"]:
        problems.append("Extensions aren't available once a payment is overdue.")
    if loan.extension_requests.filter(status__in=[ExtensionStatus.REQUESTED, ExtensionStatus.AWAITING_CONSENT]) \
            .exists():
        problems.append("You already have an extension request waiting.")
    return {"days": days, "remaining_principal": principal, **charges, "problems": problems,
            "investor_consent": e["investor_consent"], "consent_days": e["consent_days"]}


@transaction.atomic
def request_extension(loan_id, user, days, reason, request=None):
    loan = _lock_loan(loan_id)
    if loan.borrower_id != user.pk:
        raise BusinessRuleViolation("This isn't your loan.", code="not_owner")
    q = quote_extension(loan, days)
    if q["problems"]:
        raise BusinessRuleViolation(q["problems"][0], code="extension_not_allowed")
    ext = ExtensionRequest.objects.create(
        loan=loan, requested_by=user, days=days, reason=reason, remaining_principal=q["remaining_principal"],
        extension_interest=q["extension_interest"], extension_fee=q["extension_fee"],
        after_missed_payment=loan.status == "OVERDUE", rules_snapshot=rules()["extension"],
    )
    audit.record(action="extension.requested", entity_type="ExtensionRequest", entity_id=ext.pk, actor=user,
                 after={"loan": loan.reference, "days": days, "cost": q["total"]}, request=request)
    notify_admins("admin.extensions.review", "extension_requested", "Extension requested",
                  f"{loan.reference}: {days} days ({reason[:80]})", "#/admin/extensions")
    return ext


@transaction.atomic
def cancel_extension(ext_id, user):
    ext = ExtensionRequest.objects.select_for_update().get(pk=ext_id, requested_by=user)
    if ext.status not in (ExtensionStatus.REQUESTED, ExtensionStatus.AWAITING_CONSENT):
        raise BusinessRuleViolation("This request has already been decided.", code="already_decided")
    ext.status = ExtensionStatus.CANCELLED
    ext.decided_at = timezone.now()
    ext.save()
    return ext


@transaction.atomic
def review_extension(ext_id, actor, *, approve, reason, request=None):
    ext = ExtensionRequest.objects.select_for_update().select_related("loan").get(pk=ext_id)
    if ext.status != ExtensionStatus.REQUESTED:
        raise BusinessRuleViolation("This request isn't waiting for review.", code="not_requested")
    if ext.loan.borrower_id == actor.pk:
        raise BusinessRuleViolation("You can't review your own request.", code="self_review")
    ext.reviewed_by = actor
    ext.decision_reason = reason
    audit.record(action=f"extension.{'approved' if approve else 'rejected'}_by_staff",
                 entity_type="ExtensionRequest", entity_id=ext.pk, actor=actor, reason=reason, request=request)
    if not approve:
        return _decide(ext, False, reason)
    consent = ext.rules_snapshot.get("investor_consent", "NONE")
    if consent == "NONE":
        return _decide(ext, True, reason)
    ext.status = ExtensionStatus.AWAITING_CONSENT
    ext.consent_deadline = timezone.now() + timedelta(days=int(ext.rules_snapshot.get("consent_days", 3)))
    ext.save()
    what = "object" if consent == "NEGATIVE" else "agree"
    for inv in _live_investments(ext.loan):
        notify(inv.investor, "extension_vote", "An extension needs your view",
               f"The borrower of {ext.loan.reference} asked for {ext.days} more days, paying KES "
               f"{ext.extension_interest:,.2f} extra interest. Tell us by "
               f"{timezone.localtime(ext.consent_deadline):%d %b %Y} if you {what}.", "#/portfolio",
               dedupe_key=f"ext-vote-{ext.pk}")
    return ext


@transaction.atomic
def vote(ext_id, investor, agrees, comment=""):
    ext = ExtensionRequest.objects.select_for_update().select_related("loan").get(pk=ext_id)
    if ext.status != ExtensionStatus.AWAITING_CONSENT:
        raise BusinessRuleViolation("Voting on this request has closed.", code="voting_closed")
    if not ext.loan.investments.filter(investor=investor, status="ACTIVE").exists():
        raise BusinessRuleViolation("Only investors in this loan can vote.", code="not_investor")
    ExtensionVote.objects.update_or_create(extension=ext, investor=investor,
                                           defaults={"agrees": agrees, "comment": comment[:255]})
    _tally(ext)
    return ext


def _tally(ext, deadline_passed=False):
    """Weighted by outstanding principal. NEGATIVE: passes unless >50% object. EXPLICIT: needs >50% agreeing."""
    weights = {}
    for inv in _live_investments(ext.loan):
        weights[inv.investor_id] = weights.get(inv.investor_id, ZERO) + inv.outstanding
    total = sum(weights.values(), ZERO) or Decimal("1")
    votes = {v.investor_id: v.agrees for v in ext.votes.all()}
    agree = sum((w for k, w in weights.items() if votes.get(k) is True), ZERO)
    object_ = sum((w for k, w in weights.items() if votes.get(k) is False), ZERO)
    mode = ext.rules_snapshot.get("investor_consent")
    if mode == "NEGATIVE":
        if object_ * 2 > total:
            return _decide(ext, False, "Most investors (by amount owed) objected")
        if deadline_passed or (agree * 2 >= total and object_ == 0) or len(votes) == len(weights):
            return _decide(ext, True, "Investors didn't object")
    else:
        if agree * 2 > total:
            return _decide(ext, True, "Most investors (by amount owed) agreed")
        if deadline_passed or object_ * 2 >= total or len(votes) == len(weights):
            return _decide(ext, False, "Not enough investors agreed")
    return ext


def close_consent_windows(now=None):
    now = now or timezone.now()
    n = 0
    for ext_id in ExtensionRequest.objects.filter(status=ExtensionStatus.AWAITING_CONSENT,
                                                  consent_deadline__lte=now).values_list("pk", flat=True):
        with transaction.atomic():
            ext = ExtensionRequest.objects.select_for_update().select_related("loan").get(pk=ext_id)
            _tally(ext, deadline_passed=True)
            n += 1
    return n


def _decide(ext, approved, reason):
    from apps.loans import agreements
    from apps.trust_engine.services import record_extension

    ext.status = ExtensionStatus.APPROVED if approved else ExtensionStatus.REJECTED
    ext.decided_at = timezone.now()
    ext.decision_reason = reason
    ext.save()
    loan = _lock_loan(ext.loan_id)
    if approved:
        unpaid = _unpaid(loan)
        if not unpaid:
            raise BusinessRuleViolation("Nothing left to extend.", code="nothing_due")
        new_dates = calc.shift_schedule([i.due_date for i in unpaid], ext.days)
        for inst, d in zip(unpaid, new_dates):
            inst.due_date = d
            if inst.status in ("OVERDUE", "DUE") and d >= timezone.localdate():
                inst.status = "PARTIALLY_PAID" if inst.amount_paid else "UPCOMING"
            inst.save()
        first = unpaid[0]
        first.extension_interest += ext.extension_interest
        first.extension_fee += ext.extension_fee
        first.save()
        loan.extension_count += 1
        loan.total_repayable = (loan.total_repayable or ZERO) + ext.total_cost
        loan.save()
        record_extension(user=loan.borrower, loan_reference=loan.reference, extension_reference=str(ext.pk),
                         after_missed_payment=ext.after_missed_payment)
        _after_payment(loan)  # may move OVERDUE -> ACTIVE now that dates have moved
        agreements.issue(loan)
        for inv in _live_investments(loan):
            notify(inv.investor, "extension_decided", "Extension approved",
                   f"{loan.reference} was extended by {ext.days} days. You'll share the KES "
                   f"{ext.extension_interest:,.2f} extension interest.", "#/portfolio")
    notify(loan.borrower, "extension_decided", f"Extension {'approved' if approved else 'not approved'}",
           (f"Your payments on {loan.reference} have moved {ext.days} days later. KES {ext.total_cost:,.2f} in "
            "extension charges was added to your next payment. Please review the updated agreement.")
           if approved else f"Your extension request for {loan.reference} wasn't approved: {reason}.",
           f"#/loans/{loan.pk}")
    audit.record(action=f"extension.{'approved' if approved else 'rejected'}", entity_type="ExtensionRequest",
                 entity_id=ext.pk, reason=reason)
    return ext
