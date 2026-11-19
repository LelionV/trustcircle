"""Phases 9–10: notifications, chat and reports, disputes, admin reports, configuration, scheduled jobs."""
from decimal import Decimal

import pytest

from apps.accounts.models import AdminLevel, Role, User
from apps.chat.models import UserReport

from .helpers import PASSWORD, login, make_admin
from .test_phase5_8_money import approved_loan, fund, people  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def test_notifications_unread_and_mark_read(api_client, people):
    a = people["a"]
    fund(a, "1000")
    login(api_client, a)
    unread = api_client.get("/api/v1/notifications/unread/").json()
    assert unread["notifications"] >= 1
    rows = api_client.get("/api/v1/notifications/").json()["results"]
    assert any(r["title"] == "Deposit received" for r in rows)
    api_client.post("/api/v1/notifications/read/", {}, format="json")
    assert api_client.get("/api/v1/notifications/unread/").json()["notifications"] == 0


def test_chat_only_between_people_on_the_loan_and_safety_notice(api_client, people):
    loan = approved_loan(api_client, people)
    stranger = User.objects.create_user(email="stranger@example.com", password=PASSWORD, role=Role.BORROWER)
    login(api_client, stranger)
    res = api_client.post("/api/v1/chat/", {"loan_id": str(loan.pk)}, format="json")
    assert res.status_code == 422 and res.json()["error"]["code"] == "not_connected"

    login(api_client, people["a"])  # an investor browsing the marketplace may ask the borrower questions
    conv = api_client.post("/api/v1/chat/", {"loan_id": str(loan.pk)}, format="json").json()
    sent = api_client.post(f"/api/v1/chat/{conv['id']}/", {"body": "Pay me on 0712345678 instead"}, format="json")
    assert sent.status_code == 201
    msgs = api_client.get(f"/api/v1/chat/{conv['id']}/").json()["messages"]
    assert any(m["kind"] == "SYSTEM" and "outside P2P Lend" in m["body"] for m in msgs)

    login(api_client, people["borrower"])
    assert api_client.get("/api/v1/notifications/unread/").json()["chat"] >= 1
    report = api_client.post("/api/v1/reports/users/", {"message_id": sent.json()["id"], "reason": "OFF_PLATFORM",
                                                        "details": "Asked me to pay outside the app"}, format="json")
    assert report.status_code == 201
    again = api_client.post("/api/v1/reports/users/", {"user_id": str(people["a"].pk), "reason": "SPAM",
                                                       "details": "Reporting the same person twice"}, format="json")
    assert again.json()["error"]["code"] == "already_reported"

    ops = people["ops"]
    login(api_client, ops)
    r = UserReport.objects.get()
    detail = api_client.get(f"/api/v1/admin/moderation/reports/{r.pk}/").json()
    assert detail["context"] and detail["reported"]["email"] == people["a"].email
    done = api_client.post(f"/api/v1/admin/moderation/reports/{r.pk}/", {"action": "HIDE_MESSAGE", "note": "Off-platform payment request"}, format="json")
    assert done.json()["status"] == "ACTIONED"
    login(api_client, people["borrower"])
    msgs = api_client.get(f"/api/v1/chat/{conv['id']}/").json()["messages"]
    assert any(m["hidden"] for m in msgs)


def test_disputes_raised_and_resolved(api_client, people):
    login(api_client, people["borrower"])
    d = api_client.post("/api/v1/disputes/", {"category": "FEES", "subject": "Late fee",
                                              "description": "I think I was charged a late fee by mistake."}, format="json")
    assert d.status_code == 201 and d.json()["reference"].startswith("DS-")
    login(api_client, people["ops"])
    short = api_client.post(f"/api/v1/admin/disputes/{d.json()['id']}/", {"status": "RESOLVED", "resolution": "ok"}, format="json")
    assert short.status_code == 422
    ok = api_client.post(f"/api/v1/admin/disputes/{d.json()['id']}/", {"status": "RESOLVED",
                         "resolution": "Refunded the fee; the payment arrived on time."}, format="json")
    assert ok.json()["status"] == "RESOLVED"


def test_reports_exports_rules_and_jobs(api_client, people):
    fund(people["a"], "2500")
    fin = people["finance"]
    login(api_client, fin)
    m = api_client.get("/api/v1/admin/reports/").json()
    assert Decimal(m["finance"]["deposits"]) >= Decimal("2500")
    csv = api_client.get("/api/v1/admin/reports/ledger.csv")
    assert csv.status_code == 200 and b"DEPOSIT" in csv.content
    assert api_client.get("/api/v1/admin/finance/reconcile/").json()["ok"] is True
    assert api_client.put("/api/v1/admin/config/platform/", {}, format="json").status_code == 403  # finance can't

    sup = make_admin("super@example.com", AdminLevel.SUPER)
    login(api_client, sup)
    rules = api_client.get("/api/v1/admin/config/platform/").json()["parameters"]
    rules["revenue_split"] = {"investors": 80, "platform": 20, "guarantor": 10}
    bad = api_client.put("/api/v1/admin/config/platform/", {"parameters": rules, "reason": "Testing the split check"}, format="json")
    assert bad.json()["error"]["code"] == "invalid_rules"
    rules["revenue_split"] = {"investors": 80, "platform": 15, "guarantor": 5}
    ok = api_client.put("/api/v1/admin/config/platform/", {"parameters": rules, "reason": "More to investors"}, format="json")
    assert ok.json()["version"] == 2
    jobs = api_client.post("/api/v1/admin/jobs/run/", {"jobs": ["overdue", "reconcile"]}, format="json").json()
    assert jobs["reconcile"]["ok"] is True

    # Monthly rates are the default and an admin can change the basis.
    cfg = api_client.get("/api/v1/admin/config/").json()
    assert cfg["brackets"]["rate_basis"] == "MONTHLY"
    rows = cfg["brackets"]["rows"]
    res = api_client.put("/api/v1/admin/config/brackets/", {"brackets": rows, "rate_basis": "ANNUAL",
                                                             "reason": "Quote yearly rates for a while"}, format="json")
    assert res.status_code == 200
    assert api_client.get("/api/v1/admin/config/").json()["brackets"]["rate_basis"] == "ANNUAL"


def test_sandbox_confirm_only_own_payment(api_client, people):
    from apps.payments import services as payments

    intent = payments.start_deposit(people["a"], amount=Decimal("1000"), provider="SANDBOX")
    login(api_client, people["b"])
    assert api_client.post(f"/api/v1/payments/{intent.pk}/sandbox-confirm/", {"succeed": True}, format="json").status_code == 404
    login(api_client, people["a"])
    res = api_client.post(f"/api/v1/payments/{intent.pk}/sandbox-confirm/", {"succeed": True}, format="json")
    assert res.json()["status"] == "SUCCEEDED" and res.json()["balances"]["available"] == "1000.00"
