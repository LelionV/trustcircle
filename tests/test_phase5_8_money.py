"""
Phases 5–8: wallets and payments, pooled funding, guarantees with the interest
lock, agreements and pay-out, repayments and distribution, overdue/default and
guarantor claims, extensions, and the open-offers marketplace.

Every scenario ends by checking the books still balance (reconcile()).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounts.models import AdminLevel, Role, User
from apps.accounts.profiles import get_profile
from apps.guarantors.models import Guarantee, GuaranteeClaim
from apps.investments import offers as offer_services
from apps.investments import services as funding
from apps.investments.models import Investment
from apps.kyc import services as kyc_services
from apps.loans.models import Loan, LoanInstallment
from apps.payments import services as payments
from apps.repayments import services as repayments
from apps.repayments.models import DistributionLine
from apps.trust_engine.models import LoanOutcome

from .helpers import PASSWORD, login, make_admin, submit_kyc, ready_borrower

pytestmark = pytest.mark.django_db
D = Decimal


# --- builders -------------------------------------------------------------------------------

def verified(email, role, income="140000", reviewer=None):
    user = User.objects.create_user(email=email, password=PASSWORD, role=role, first_name=email.split("@")[0].title(),
                                    last_name="Test", phone_number=f"+2547{abs(hash(email)) % 10**8:08d}",
                                    is_email_verified=True, is_phone_verified=True)
    profile = get_profile(user)
    if hasattr(profile, "monthly_income"):
        profile.monthly_income = D(income)
        profile.save()
    reviewer = reviewer or make_admin(f"kyc-{email}", AdminLevel.OPERATIONS)
    kyc_services.approve(actor=reviewer, submission_id=submit_kyc(user, number=str(abs(hash(email)) % 10**8)).pk)
    user.refresh_from_db()
    return user


def fund(user, amount):
    """Deposit through the sandbox provider and confirm it, as the provider callback would."""
    intent = payments.start_deposit(user, amount=D(amount), provider="SANDBOX")
    return payments.settle(intent.provider_reference, succeeded=True, amount=D(amount))


def available(user):
    return ledger.balances(user)["available"]


def assert_books_balance():
    result = ledger.reconcile()
    assert result["ok"], result["problems"]


@pytest.fixture
def people():
    ops = make_admin("ops@example.com", AdminLevel.OPERATIONS)
    finance = make_admin("finance@example.com", AdminLevel.FINANCE)
    borrower = ready_borrower(reviewer=ops)
    guarantor = verified("grace@example.com", Role.GUARANTOR, reviewer=ops)
    a = verified("ann@example.com", Role.INVESTOR, reviewer=ops)
    b = verified("ben@example.com", Role.INVESTOR, reviewer=ops)
    return {"ops": ops, "finance": finance, "borrower": borrower, "guarantor": guarantor, "a": a, "b": b}


def approved_loan(client, p, *, guarantor=True, amount="40000", term=6):
    login(client, p["borrower"])
    product = client.get("/api/v1/loans/products/").json()[0]["id"]
    loan = client.post("/api/v1/loans/", {
        "product": product, "amount": amount, "term_months": term, "repayment_frequency": "MONTHLY",
        "purpose": "BUSINESS", "employment_status": "EMPLOYED", "monthly_income": "85000.00",
        "monthly_obligations": "15000.00", "guarantor_email": p["guarantor"].email if guarantor else "",
    }, format="json").json()
    assert client.post(f"/api/v1/loans/{loan['id']}/submit/").status_code == 200
    login(client, p["ops"])
    client.post(f"/api/v1/admin/loans/{loan['id']}/start-review/")
    res = client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Verified income covers it"}, format="json")
    assert res.status_code == 200, res.content
    assert client.post(f"/api/v1/admin/loans/{loan['id']}/publish/").status_code == 200
    return Loan.objects.get(pk=loan["id"])


def active_loan(client, p):
    """A guaranteed 40,000 loan funded 30k/10k by two investors and paid out."""
    loan = approved_loan(client, p)
    fund(p["guarantor"], "20000")
    g = Guarantee.objects.get(loan=loan)
    from apps.guarantors.services import respond
    respond(g.pk, p["guarantor"], accept=True)
    fund(p["a"], "30000")
    fund(p["b"], "10000")
    funding.invest(p["a"], loan.pk, D("30000"))
    funding.invest(p["b"], loan.pk, D("10000"))
    from apps.loans import agreements
    loan.refresh_from_db()
    agreements.accept(loan, p["borrower"])
    funding.disburse(loan.pk, p["finance"])
    loan.refresh_from_db()
    return loan


# --- wallets and payments ----------------------------------------------------------------------

def test_deposit_is_credited_only_after_confirmation(people):
    a = people["a"]
    intent = payments.start_deposit(a, amount=D("5000"), provider="SANDBOX")
    assert available(a) == 0 and intent.status == "PENDING"
    payments.settle(intent.provider_reference, succeeded=True, amount=D("5000"))
    payments.settle(intent.provider_reference, succeeded=True, amount=D("5000"))  # duplicate callback: ignored
    assert available(a) == D("5000.00")
    failed = payments.start_deposit(a, amount=D("700"), provider="SANDBOX")
    payments.settle(failed.provider_reference, succeeded=False, message="Cancelled by user")
    mismatch = payments.start_deposit(a, amount=D("900"), provider="SANDBOX")
    assert payments.settle(mismatch.provider_reference, succeeded=True, amount=D("1")).status == "FAILED"
    assert available(a) == D("5000.00")
    assert_books_balance()


def test_withdrawal_fee_threshold_approval_and_rejection(api_client, people):
    a, finance = people["a"], people["finance"]
    fund(a, "100000")
    small = payments.request_withdrawal(a, amount=D("1000"), provider="SANDBOX")
    assert small.status == "PROCESSING" and small.fee == D("20.00")  # 1%, minimum 20
    payments.settle(small.provider_reference, succeeded=True)
    big = payments.request_withdrawal(a, amount=D("60000"), provider="SANDBOX")
    assert big.status == "AWAITING_APPROVAL"
    assert ledger.balances(a)["pending"] == D("60000.00")
    with pytest.raises(Exception):
        payments.approve_withdrawal(big.pk, a)  # nobody approves their own
    payments.reject_withdrawal(big.pk, finance, "Please confirm the destination number first")
    assert available(a) == D("100000") - D("1020")  # rejected amount and its fee come back
    assert ledger.balances(a)["pending"] == 0
    login(api_client, finance)
    again = payments.request_withdrawal(a, amount=D("60000"), provider="SANDBOX")
    res = api_client.post(f"/api/v1/admin/payments/{again.pk}/decision/", {"approve": True}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "PROCESSING"
    assert_books_balance()


def test_transfer_charges_fee_and_cannot_overdraw(people):
    a, b = people["a"], people["b"]
    fund(a, "500")
    payments.transfer(a, recipient_email=b.email, amount=D("200"))
    assert available(a) == D("290.00") and available(b) == D("200.00")  # KES 10 fee
    with pytest.raises(ledger.InsufficientFunds):
        payments.transfer(a, recipient_email=b.email, amount=D("300"))
    assert_books_balance()


# --- funding, guarantee lock, agreement, pay-out ------------------------------------------------------

def test_guaranteed_loan_full_lifecycle(api_client, people):
    p = people
    loan = approved_loan(api_client, p)
    g = Guarantee.objects.get(loan=loan)
    assert g.status == "REQUESTED"
    interest = loan.total_interest

    # The guarantor needs the borrower's total interest available, and it gets locked.
    login(api_client, p["guarantor"])
    res = api_client.post(f"/api/v1/guarantees/{g.pk}/respond/", {"accept": True}, format="json")
    assert res.json()["error"]["code"] == "insufficient_funds"
    fund(p["guarantor"], "20000")
    assert api_client.post(f"/api/v1/guarantees/{g.pk}/respond/", {"accept": True}, format="json").status_code == 200
    assert ledger.balances(p["guarantor"])["locked"] == interest
    assert available(p["guarantor"]) == D("20000") - interest

    # Pooled funding, never overfunded.
    fund(p["a"], "30000")
    fund(p["b"], "20000")
    funding.invest(p["a"], loan.pk, D("30000"))
    login(api_client, p["b"])
    over = api_client.post(f"/api/v1/marketplace/{loan.pk}/invest/", {"amount": "15000"}, format="json")
    assert over.json()["error"]["code"] == "overfunding"
    assert api_client.post(f"/api/v1/marketplace/{loan.pk}/invest/", {"amount": "10000"}, format="json").status_code == 201
    loan.refresh_from_db()
    assert loan.status == "READY_FOR_DISBURSEMENT" and loan.funded_amount == loan.amount
    assert ledger.balances(p["a"])["invested"] == D("30000.00")

    # No pay-out before the borrower accepts the agreement.
    login(api_client, p["finance"])
    early = api_client.post(f"/api/v1/admin/loans/{loan.pk}/disburse/")
    assert early.json()["error"]["code"] == "agreement_pending"
    login(api_client, p["borrower"])
    assert "LOAN AGREEMENT" in api_client.get(f"/api/v1/loans/{loan.pk}/agreement/").json()["text"]
    api_client.post(f"/api/v1/loans/{loan.pk}/agreement/")
    login(api_client, p["finance"])
    assert api_client.post(f"/api/v1/admin/loans/{loan.pk}/disburse/").json()["status"] == "ACTIVE"
    assert available(p["borrower"]) == D("40000.00")
    assert ledger.balances(p["a"])["invested"] == 0
    assert LoanInstallment.objects.filter(loan=loan, due_date__gt=timezone.localdate()).count() == 6
    assert_books_balance()

    # First installment: paid straight out, by contribution (30k : 10k).
    first = loan.installments.order_by("sequence").first()
    login(api_client, p["borrower"])
    res = api_client.post(f"/api/v1/loans/{loan.pk}/repay/", {"amount": str(first.total)}, format="json")
    assert res.status_code == 201, res.content
    lines = DistributionLine.objects.filter(loan=loan)
    total_out = sum((l.total for l in lines), D("0"))
    assert total_out == first.total  # every cent accounted for
    inv_a = Investment.objects.get(loan=loan, investor=p["a"])
    inv_b = Investment.objects.get(loan=loan, investor=p["b"])
    assert inv_a.principal_repaid + inv_b.principal_repaid == first.principal
    assert abs(inv_a.principal_repaid - 3 * inv_b.principal_repaid) <= D("0.03")
    g.refresh_from_db()
    assert g.commission_earned > 0  # 5% of interest goes to the guarantor

    # Pay everything else now: loan completes early, lock released, trust bonus recorded.
    owed = repayments.outstanding(loan)["total"]
    fund(p["borrower"], str(owed))
    repayments.repay(loan.pk, p["borrower"], owed)
    loan.refresh_from_db()
    g.refresh_from_db()
    assert loan.status == "COMPLETED"
    assert ledger.balances(p["guarantor"])["locked"] == 0 and g.status == "RELEASED"
    assert set(Investment.objects.filter(loan=loan).values_list("status", flat=True)) == {"COMPLETED"}
    outcome = LoanOutcome.objects.get(loan_reference=loan.reference)
    assert outcome.bonus_points > 0  # repaid well before the final due date
    assert_books_balance()


def test_funding_expiry_refunds_investors(api_client, people):
    loan = approved_loan(api_client, people)
    fund(people["a"], "5000")
    funding.invest(people["a"], loan.pk, D("5000"))
    Loan.objects.filter(pk=loan.pk).update(funding_expires_at=timezone.now() - timedelta(minutes=1))
    assert loan.reference in funding.expire_funding_rounds()
    loan.refresh_from_db()
    assert loan.status == "CANCELLED" and available(people["a"]) == D("5000.00")
    assert Guarantee.objects.get(loan=loan).status == "RELEASED"
    assert_books_balance()


# --- overdue, default, guarantor claim ---------------------------------------------------------------

def test_overdue_late_fee_default_and_claim_uses_lock_first(api_client, people):
    loan = active_loan(api_client, people)
    first = loan.installments.order_by("sequence").first()
    lock = ledger.balances(people["guarantor"])["locked"]

    summary = repayments.process_overdue(today=first.due_date + timedelta(days=5))
    loan.refresh_from_db()
    first.refresh_from_db()
    assert loan.status == "OVERDUE" and first.late_fee > 0 and summary["late_fees"] >= 1

    repayments.process_overdue(today=first.due_date + timedelta(days=61))
    loan.refresh_from_db()
    assert loan.status == "DEFAULTED"
    claim = GuaranteeClaim.objects.get(guarantee__loan=loan)
    assert claim.recovered > 0 and claim.recovered >= min(lock, claim.amount)  # locked interest went first
    assert ledger.balances(people["guarantor"])["locked"] == 0
    recovered = sum(Investment.objects.filter(loan=loan).values_list("recovered", flat=True))
    assert recovered == claim.recovered
    assert LoanOutcome.objects.get(loan_reference=loan.reference).outcome == "DEFAULTED"
    assert_books_balance()


# --- extensions ----------------------------------------------------------------------------------

def test_extension_needs_review_and_investor_consent(api_client, people):
    loan = active_loan(api_client, people)
    before = list(loan.installments.order_by("sequence").values_list("due_date", flat=True))
    login(api_client, people["borrower"])
    quote = api_client.get(f"/api/v1/loans/{loan.pk}/extension/", {"days": 30}).json()
    assert D(quote["extension_interest"]) > 0 and not quote["problems"]
    api_client.post(f"/api/v1/loans/{loan.pk}/extension/", {"days": 30, "reason": "Salary is paid late this month"}, format="json")
    ext = loan.extension_requests.get()
    login(api_client, people["ops"])
    api_client.post(f"/api/v1/admin/extensions/{ext.pk}/decision/", {"approve": True, "reason": "Reasonable request"}, format="json")
    ext.refresh_from_db()
    assert ext.status == "AWAITING_CONSENT"  # default rules: approved unless investors object
    for investor in (people["a"], people["b"]):
        login(api_client, investor)
        api_client.post(f"/api/v1/extensions/{ext.pk}/vote/", {"agrees": True}, format="json")
    ext.refresh_from_db()
    loan.refresh_from_db()
    assert ext.status == "APPROVED" and loan.extension_count == 1
    after = list(loan.installments.order_by("sequence").values_list("due_date", flat=True))
    assert all((n - o).days == 30 for o, n in zip(before, after))
    assert loan.installments.order_by("sequence").first().extension_interest == ext.extension_interest
    assert loan.agreements.count() == 2  # a new agreement version for the new terms


def test_extension_rejected_when_most_investors_object(api_client, people):
    loan = active_loan(api_client, people)
    ext = repayments.request_extension(loan.pk, people["borrower"], 20, "Need a little more time")
    repayments.review_extension(ext.pk, people["ops"], approve=True, reason="Sent to investors")
    repayments.vote(ext.pk, people["a"], False)  # holds 75% of the loan
    ext.refresh_from_db()
    assert ext.status == "REJECTED"


# --- open-offers marketplace -----------------------------------------------------------------------

def test_open_offers_weighted_rate_and_interest_by_rate(api_client, people):
    p = people
    loan = approved_loan(api_client, p, guarantor=False)
    assert loan.funding_mode == "OFFERS" and not loan.guarantees.exists()
    fund(p["a"], "25000")
    fund(p["b"], "15000")
    with pytest.raises(Exception):
        offer_services.make_offer(p["a"], loan.pk, amount=D("25000"), rate=D("50"))  # above the admin's maximum
    login(api_client, p["a"])
    assert api_client.post(f"/api/v1/marketplace/{loan.pk}/invest/", {"amount": "1000"}, format="json") \
        .json()["error"]["code"] == "offers_only"
    o1 = offer_services.make_offer(p["a"], loan.pk, amount=D("25000"), rate=D("3.00"))
    o2 = offer_services.make_offer(p["b"], loan.pk, amount=D("15000"), rate=D("5.00"))
    assert ledger.balances(p["a"])["invested"] == D("25000.00")  # held while open

    # The borrower and investor can talk about the offer; the offer shows in their chat.
    login(api_client, p["borrower"])
    chats = api_client.get("/api/v1/chat/").json()
    assert any(c["loan"] and c["loan"]["reference"] == loan.reference for c in chats)

    offer_services.accept_offer(o1.pk, p["borrower"])
    offer_services.accept_offer(o2.pk, p["borrower"])
    loan.refresh_from_db()
    assert loan.annual_rate == D("3.75")  # (25k×3 + 15k×5) / 40k
    assert loan.status == "READY_FOR_DISBURSEMENT"
    from apps.loans import agreements
    agreements.accept(loan, p["borrower"])
    funding.disburse(loan.pk, p["finance"])
    loan.refresh_from_db()
    first = loan.installments.order_by("sequence").first()
    repayments.repay(loan.pk, p["borrower"], first.total)
    lines = {l.recipient_id: l for l in DistributionLine.objects.filter(loan=loan, role="INVESTOR")}
    # 25k at 3% and 15k at 5% earn the same interest (75,000 = 75,000 weight)
    assert abs(lines[p["a"].pk].interest - lines[p["b"].pk].interest) <= D("0.01")
    assert lines[p["a"].pk].principal > lines[p["b"].pk].principal
    assert_books_balance()


def test_guarantor_can_invest_but_not_in_their_own_guarantee(api_client, people):
    p = people
    loan = approved_loan(api_client, p)
    fund(p["guarantor"], "5000")
    login(api_client, p["guarantor"])
    assert api_client.get("/api/v1/marketplace/").status_code == 200
    res = api_client.post(f"/api/v1/marketplace/{loan.pk}/invest/", {"amount": "1000"}, format="json")
    assert res.json()["error"]["code"] == "conflict"


def test_guarantor_can_accept_before_approval_and_lock_follows_the_approved_interest(api_client, people):
    p = people
    login(api_client, p["borrower"])
    product = api_client.get("/api/v1/loans/products/").json()[0]["id"]
    loan = api_client.post("/api/v1/loans/", {
        "product": product, "amount": "40000", "term_months": 6, "repayment_frequency": "MONTHLY",
        "purpose": "BUSINESS", "employment_status": "EMPLOYED", "monthly_income": "85000.00",
        "monthly_obligations": "15000.00", "guarantor_email": p["guarantor"].email,
    }, format="json").json()
    api_client.post(f"/api/v1/loans/{loan['id']}/submit/")
    # Pretend the quote at submission was lower than what approval will set.
    Loan.objects.filter(pk=loan["id"]).update(total_interest=D("100.00"))

    login(api_client, p["guarantor"])
    rows = api_client.get("/api/v1/guarantees/").json()["guarantees"]
    assert len(rows) == 1 and rows[0]["status"] == "REQUESTED" and rows[0]["can_accept"] is True
    fund(p["guarantor"], "20000")
    ok = api_client.post(f"/api/v1/guarantees/{rows[0]['id']}/respond/", {"accept": True}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "ACCEPTED"
    assert ledger.balances(p["guarantor"])["locked"] == D("100.00")

    login(api_client, p["ops"])
    api_client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Verified income covers it"}, format="json")
    approved = Loan.objects.get(pk=loan["id"])
    assert ledger.balances(p["guarantor"])["locked"] == approved.total_interest  # the difference was locked
    assert available(p["guarantor"]) == D("20000") - approved.total_interest
    assert_books_balance()


def test_older_loans_get_their_guarantee_request_backfilled(api_client, people):
    loan = approved_loan(api_client, people)
    Guarantee.objects.filter(loan=loan).delete()  # as if created before requests were sent automatically
    login(api_client, people["guarantor"])
    rows = api_client.get("/api/v1/guarantees/").json()["guarantees"]
    assert [r["loan"] for r in rows] == [loan.reference]
