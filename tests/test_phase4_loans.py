"""Phase 4: loan products, quotes, applications, review, rate locking and the marketplace."""
from decimal import Decimal

import pytest

from apps.accounts.models import AdminLevel, Role
from apps.loans.models import Loan, LoanInstallment, LoanStatus
from apps.trust_engine import services as trust

from .helpers import PASSWORD, login, make_admin, make_guarantor, png_file, ready_borrower

pytestmark = pytest.mark.django_db


def product_id(client):
    return client.get("/api/v1/loans/products/").json()[0]["id"]


def application(client, **overrides):
    data = {
        "product": product_id(client), "amount": "40000", "term_months": 6, "repayment_frequency": "MONTHLY",
        "purpose": "BUSINESS", "employment_status": "EMPLOYED", "monthly_income": "85000.00",
        "monthly_obligations": "15000.00", "guarantor_email": "guarantor@example.com",
    }
    data.update(overrides)
    return data


@pytest.fixture
def setup(api_client):
    make_guarantor()
    user = ready_borrower()
    login(api_client, user)
    return user


def test_quote_prices_from_trust_bracket(api_client, setup):
    q = api_client.post("/api/v1/loans/quote/", application(api_client), format="json").json()
    assert q["trust_score"] == 50 and q["annual_rate"] == "3.50" and q["rate_basis"] == "MONTHLY"
    s = q["schedule"]
    assert s["installment_count"] == 6
    assert Decimal(s["total_repayable"]) == Decimal("40000.00") + Decimal(s["total_interest"])
    assert q["can_submit"] is True


def test_quote_flags_unaffordable_and_unverified(api_client, borrower):
    login(api_client, borrower)  # not verified at all
    q = api_client.post("/api/v1/loans/quote/", application(api_client, amount="150000", term_months=1,
                                                             monthly_income="20000.00", monthly_obligations="5000.00"),
                        format="json").json()
    codes = {p["code"] for p in q["problems"]}
    assert {"kyc_required", "email_unverified", "phone_unverified"} <= codes
    assert q["can_submit"] is False and q["schedule"] is None  # no score, no rate


def test_affordability_blocks_large_installments(api_client, setup):
    q = api_client.post("/api/v1/loans/quote/", application(api_client, amount="150000", term_months=2), format="json").json()
    assert "not_affordable" in {p["code"] for p in q["problems"]}


def test_draft_submit_review_approve_publish(api_client, setup):
    borrower = setup
    loan = api_client.post("/api/v1/loans/", application(api_client), format="json").json()
    assert loan["status"] == "DRAFT" and loan["reference"].startswith("LN-")
    second = api_client.post("/api/v1/loans/", application(api_client), format="json")
    assert second.json()["error"]["code"] == "draft_exists"

    submitted = api_client.post(f"/api/v1/loans/{loan['id']}/submit/").json()
    assert submitted["status"] == "SUBMITTED" and submitted["annual_rate"] == "3.50" and submitted["rate_basis"] == "MONTHLY"
    assert submitted["trust_score_snapshot"] == 50

    ops = make_admin("ops2@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)
    assert api_client.post(f"/api/v1/admin/loans/{loan['id']}/start-review/").json()["status"] == "UNDER_REVIEW"
    approved = api_client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Affordable on verified pay"}, format="json")
    assert approved.status_code == 200, approved.content
    body = approved.json()
    assert body["status"] == "APPROVED" and body["terms_locked"] is True
    assert LoanInstallment.objects.filter(loan_id=loan["id"]).count() == 6

    # A later rise in the trust score never changes the approved loan's rate.
    for n in range(1, 7):
        from datetime import date, timedelta
        due = date(2026, 1, 1) + timedelta(days=30 * n)
        trust.record_installment_payment(user=borrower, loan_reference="OLD", installment_reference=f"OLD-{n}",
                                         due_date=due, paid_on=due - timedelta(days=8),
                                         amount_due=Decimal("5000"), amount_paid=Decimal("5000"))
    assert Loan.objects.get(pk=loan["id"]).annual_rate == Decimal("3.50")

    published = api_client.post(f"/api/v1/admin/loans/{loan['id']}/publish/").json()
    assert published["status"] == "PUBLISHED" and published["funding_expires_at"]


def test_invalid_transitions_and_self_review(api_client, setup):
    loan = api_client.post("/api/v1/loans/", application(api_client), format="json").json()
    ops = make_admin("ops2@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)
    res = api_client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Approving a draft"}, format="json")
    assert res.status_code in (404, 422)  # drafts aren't visible to admins and can't be approved
    publish = api_client.post(f"/api/v1/admin/loans/{loan['id']}/publish/")
    assert publish.status_code == 422


def test_no_guarantor_goes_to_open_offers(api_client, setup):
    loan = api_client.post("/api/v1/loans/", application(api_client, guarantor_email=""), format="json").json()
    res = api_client.post(f"/api/v1/loans/{loan['id']}/submit/")
    assert res.status_code == 200, res.content
    assert res.json()["funding_mode"] == "OFFERS"


def test_guarantor_must_be_a_guarantor_account(api_client, setup):
    res = api_client.post("/api/v1/loans/", application(api_client, guarantor_email="nobody@example.com"), format="json")
    assert res.json()["error"]["code"] == "guarantor_not_found"


def test_one_application_in_review_at_a_time(api_client, setup):
    first = api_client.post("/api/v1/loans/", application(api_client), format="json").json()
    api_client.post(f"/api/v1/loans/{first['id']}/submit/")
    second = api_client.post("/api/v1/loans/", application(api_client, amount="10000"), format="json").json()
    res = api_client.post(f"/api/v1/loans/{second['id']}/submit/")
    assert res.json()["error"]["code"] == "application_in_review"


def test_borrower_cancel_and_reject_with_reason(api_client, setup):
    loan = api_client.post("/api/v1/loans/", application(api_client), format="json").json()
    api_client.post(f"/api/v1/loans/{loan['id']}/submit/")
    ops = make_admin("ops2@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)
    short = api_client.post(f"/api/v1/admin/loans/{loan['id']}/reject/", {"reason": "no"}, format="json")
    assert short.status_code == 400
    rejected = api_client.post(f"/api/v1/admin/loans/{loan['id']}/reject/", {"reason": "Income couldn't be confirmed"}, format="json")
    assert rejected.json()["status"] == "REJECTED"
    login(api_client, setup)
    assert api_client.post(f"/api/v1/loans/{loan['id']}/cancel/", {}, format="json").status_code == 422


def test_manual_pricing_for_critical_bracket(api_client, setup):
    borrower = setup
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    api_client.post(f"/api/v1/admin/users/{borrower.pk}/trust/adjust/", {"points": -20, "reason": "Fraud check pending"}, format="json")
    api_client.post(f"/api/v1/admin/users/{borrower.pk}/trust/adjust/", {"points": -15, "reason": "Second adjustment down"}, format="json")
    borrower.trust_score.refresh_from_db()
    assert borrower.trust_score.score == 15  # critical bracket: manual review

    login(api_client, borrower)
    loan = api_client.post("/api/v1/loans/", application(api_client, amount="5000"), format="json").json()
    sub = api_client.post(f"/api/v1/loans/{loan['id']}/submit/").json()
    assert sub["requires_manual_pricing"] is True and sub["annual_rate"] is None

    ops = make_admin("ops2@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)
    missing = api_client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Manual review done"}, format="json")
    assert missing.json()["error"]["code"] == "manual_rate_required"
    ok = api_client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Manual review done", "annual_rate": "5.00"}, format="json")
    assert ok.json()["annual_rate"] == "5.00"


def test_marketplace_shows_published_loans_without_identity(api_client, setup):
    loan = api_client.post("/api/v1/loans/", application(api_client), format="json").json()
    api_client.post(f"/api/v1/loans/{loan['id']}/submit/")
    ops = make_admin("ops2@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)
    api_client.post(f"/api/v1/admin/loans/{loan['id']}/approve/", {"reason": "Looks good to us"}, format="json")

    investor = make_admin("unused@example.com", AdminLevel.SUPPORT)
    investor.role, investor.admin_level = Role.INVESTOR, AdminLevel.NONE
    investor.save()
    login(api_client, investor)
    assert api_client.get("/api/v1/marketplace/").json()["count"] == 0  # approved but not yet published

    login(api_client, ops)
    api_client.post(f"/api/v1/admin/loans/{loan['id']}/publish/")
    login(api_client, investor)
    item = api_client.get("/api/v1/marketplace/").json()["results"][0]
    assert item["borrower"]["display_name"] == "Brenda W."
    assert "email" not in str(item["borrower"]).lower()
    assert item["funding"]["percent"] == 0

    login(api_client, setup)
    assert api_client.get("/api/v1/marketplace/").status_code == 403  # borrowers can't browse investments


def test_loan_documents_are_private(api_client, setup, make_user):
    loan = api_client.post("/api/v1/loans/", application(api_client), format="json").json()
    doc = api_client.post(f"/api/v1/loans/{loan['id']}/documents/", {"file": png_file(), "description": "Payslip"}, format="multipart")
    assert doc.status_code == 201
    url = doc.json()["url"]
    assert api_client.get(url).status_code == 200
    other = make_user(email="other@example.com")
    api_client.credentials()
    res = api_client.post("/api/v1/auth/token/", {"email": other.email, "password": PASSWORD}, format="json")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
    assert api_client.get(url).status_code == 404


def test_product_management(api_client):
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    res = api_client.post("/api/v1/admin/products/", {
        "name": "Farm input loan", "min_amount": "5000", "max_amount": "300000", "min_term_months": 3,
        "max_term_months": 9, "frequencies": ["MONTHLY"], "interest_method": "FLAT", "rate_basis": "ANNUAL",
        "requires_guarantor": False, "funding_period_days": 21, "max_installment_share": "40", "max_open_loans": 1,
        "is_active": True,
    }, format="json")
    assert res.status_code == 201, res.content
    bad = api_client.patch(f"/api/v1/admin/products/{res.json()['id']}/", {"max_amount": "100"}, format="json")
    assert bad.status_code == 400
