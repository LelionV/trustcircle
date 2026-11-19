"""Phase 3: trust engine, risk engine, interest brackets and configuration."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounts.models import AdminLevel
from apps.audit.models import AuditLog
from apps.loans.models import InterestBracketSet
from apps.risk_engine.models import RiskConfig
from apps.trust_engine import services as trust
from apps.trust_engine.models import RepaymentRecord, TrustConfig, TrustEvent

from .helpers import login, make_admin, ready_borrower

pytestmark = pytest.mark.django_db


def pay(user, loan, n, days_early, amount="5000"):
    due = date(2026, 1, 1) + timedelta(days=30 * n)
    return trust.record_installment_payment(
        user=user, loan_reference=loan, installment_reference=f"{loan}-{n}", due_date=due,
        paid_on=due - timedelta(days=days_early), amount_due=Decimal(amount), amount_paid=Decimal(amount),
    )


def test_unverified_borrower_has_no_score(borrower):
    score = trust.recalculate_trust(borrower)
    assert score.score is None


def test_new_verified_borrower_starts_at_initial_score():
    user = ready_borrower()
    assert user.trust_score.score == 50
    assert user.trust_score.confidence == "NEW"


def test_early_repayments_raise_score_and_are_recorded():
    user = ready_borrower()
    for n in range(1, 7):
        pay(user, "LN-A", n, days_early=8)
    trust.record_loan_outcome(user=user, loan_reference="LN-A", outcome="COMPLETED")
    user.trust_score.refresh_from_db()
    assert user.trust_score.score > 60
    assert user.trust_score.early_payments == 6
    events = TrustEvent.objects.filter(user=user, event_type="INSTALLMENT_PAID")
    assert events.count() == 6
    assert all(e.reason.startswith("Installment paid 8 days early") for e in events)


def test_late_payments_lower_score():
    user = ready_borrower()
    for n in range(1, 5):
        pay(user, "LN-B", n, days_early=-10)
    user.trust_score.refresh_from_db()
    assert user.trust_score.score < 50
    assert user.trust_score.late_payments == 4


def test_same_installment_never_counts_twice():
    user = ready_borrower()
    pay(user, "LN-C", 1, days_early=8)
    pay(user, "LN-C", 1, days_early=8)
    assert RepaymentRecord.objects.filter(user=user).count() == 1


def test_small_or_partial_installments_do_not_count():
    user = ready_borrower()
    small = pay(user, "LN-D", 1, days_early=8, amount="100")
    assert small.counted is False
    due = date(2026, 3, 1)
    partial = trust.record_installment_payment(
        user=user, loan_reference="LN-D", installment_reference="LN-D-2", due_date=due, paid_on=due,
        amount_due=Decimal("5000"), amount_paid=Decimal("4000"))
    assert partial.counted is False
    user.trust_score.refresh_from_db()
    assert user.trust_score.installments_counted == 0


def test_reward_cap_per_loan():
    user = ready_borrower()
    records = [pay(user, "LN-E", n, days_early=10) for n in range(1, 9)]  # 8 x +4 = 32 > cap 24
    assert sum(r.counted_points for r in records) == 24


def test_default_penalty():
    user = ready_borrower()
    pay(user, "LN-F", 1, days_early=-20)
    trust.record_loan_outcome(user=user, loan_reference="LN-F", outcome="DEFAULTED")
    user.trust_score.refresh_from_db()
    assert user.trust_score.score <= 25
    assert user.trust_score.defaults == 1


def test_extension_penalties_escalate():
    user = ready_borrower()
    first = trust.record_extension(user=user, loan_reference="LN-G", extension_reference="X1", after_missed_payment=False)
    second = trust.record_extension(user=user, loan_reference="LN-G", extension_reference="X2", after_missed_payment=True)
    assert first.penalty_points == 0
    assert second.penalty_points == 3 + 2


def test_trust_history_is_append_only():
    user = ready_borrower()
    event = TrustEvent.objects.filter(user=user).first()
    with pytest.raises(PermissionError):
        event.save()
    with pytest.raises(PermissionError):
        TrustEvent.objects.filter(user=user).update(reason="x")


def test_my_trust_endpoint(api_client):
    user = ready_borrower()
    login(api_client, user)
    body = api_client.get("/api/v1/trust/me/").json()
    assert body["score"] == 50 and body["bracket"]["label"] == "High risk"
    assert body["next_bracket"]["min_score"] == 60
    assert {c["key"] for c in body["breakdown"]["components"]} >= {"punctuality", "kyc"}


def test_manual_adjustment_is_audited_and_bounded(api_client):
    user = ready_borrower()
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    too_big = api_client.post(f"/api/v1/admin/users/{user.pk}/trust/adjust/", {"points": 50, "reason": "Way too big a change"}, format="json")
    assert too_big.status_code == 422
    ok = api_client.post(f"/api/v1/admin/users/{user.pk}/trust/adjust/", {"points": 5, "reason": "Verified employer reference"}, format="json")
    assert ok.status_code == 200 and ok.json()["trust"]["score"] == 55
    assert AuditLog.objects.filter(action="trust.adjusted").exists()

    ops = make_admin("ops@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)  # operations can override risk but not trust
    assert api_client.post(f"/api/v1/admin/users/{user.pk}/trust/adjust/", {"points": 1, "reason": "Not allowed here"}, format="json").status_code == 403


def test_risk_assessment_and_override(api_client):
    user = ready_borrower(income="30000", obligations="20000")
    assert user.risk_profile.score > 0
    ops = make_admin("ops@example.com", AdminLevel.OPERATIONS)
    login(api_client, ops)
    res = api_client.post(f"/api/v1/admin/users/{user.pk}/risk/override/", {"classification": "HIGH", "reason": "Recent salary arrears"}, format="json")
    assert res.status_code == 200
    risk = res.json()["risk"]
    assert risk["classification"] == "HIGH" and risk["is_overridden"] is True
    cleared = api_client.post(f"/api/v1/admin/users/{user.pk}/risk/override/", {"classification": "", "reason": "Arrears settled now"}, format="json")
    assert cleared.json()["risk"]["is_overridden"] is False


def test_bracket_configuration_is_versioned(api_client):
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    cfg = api_client.get("/api/v1/admin/config/").json()
    rows = cfg["brackets"]["rows"]
    rows[2]["annual_rate"] = "17.50"
    res = api_client.put("/api/v1/admin/config/brackets/", {"brackets": rows, "reason": "Funding costs fell this quarter"}, format="json")
    assert res.status_code == 200 and res.json()["version"] == 2
    assert InterestBracketSet.objects.count() == 2
    assert InterestBracketSet.objects.get(is_active=True).version == 2

    gap = [dict(r) for r in rows]
    gap[1]["max_score"] = 30
    bad = api_client.put("/api/v1/admin/config/brackets/", {"brackets": gap, "reason": "This leaves a gap"}, format="json")
    assert bad.status_code == 422 and "covered" in bad.json()["error"]["message"]


def test_trust_rules_change_rescores_borrowers(api_client):
    user = ready_borrower()
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    params = api_client.get("/api/v1/admin/config/").json()["trust"]["parameters"]
    params["initial_score"] = 55
    res = api_client.put("/api/v1/admin/config/trust/", {"parameters": params, "reason": "Raise the starting score"}, format="json")
    assert res.status_code == 200 and res.json()["borrowers_rescored"] >= 1
    user.trust_score.refresh_from_db()
    assert user.trust_score.score == 55
    assert TrustConfig.objects.filter(is_active=True).get().version == 2

    params["weights"]["kyc"] = 99
    bad = api_client.put("/api/v1/admin/config/trust/", {"parameters": params, "reason": "Weights now broken"}, format="json")
    assert bad.status_code == 422


def test_risk_rules_validation(api_client):
    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    params = api_client.get("/api/v1/admin/config/").json()["risk"]["parameters"]
    params["thresholds"][1]["min"] = 25
    res = api_client.put("/api/v1/admin/config/risk/", {"parameters": params, "reason": "Introduce a gap by mistake"}, format="json")
    assert res.status_code == 422
    assert RiskConfig.objects.count() == 1


def test_config_is_super_admin_only(api_client):
    login(api_client, make_admin("finance@example.com", AdminLevel.FINANCE))
    assert api_client.get("/api/v1/admin/config/").status_code == 403
