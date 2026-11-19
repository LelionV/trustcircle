import pytest

from apps.accounts.models import AdminLevel, Role, User
from apps.accounts.permissions import permissions_for
from apps.audit.models import AuditLog

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def login(client, user):
    client.credentials()
    res = client.post("/api/v1/auth/token/", {"email": user.email, "password": PASSWORD}, format="json")
    assert res.status_code == 200, res.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
    return res.json()


@pytest.fixture
def admins(make_user):
    def admin(level, email):
        return make_user(email=email, role=Role.ADMIN, admin_level=level, is_staff=True)

    return {
        "support": admin(AdminLevel.SUPPORT, "support@example.com"),
        "operations": admin(AdminLevel.OPERATIONS, "ops@example.com"),
        "finance": admin(AdminLevel.FINANCE, "finance@example.com"),
        "super": admin(AdminLevel.SUPER, "super@example.com"),
    }


# --- Permission matrix ---------------------------------------------------

def test_role_permissions_are_separated(make_user):
    borrower = make_user(email="b@example.com", role=Role.BORROWER)
    investor = make_user(email="i@example.com", role=Role.INVESTOR)
    guarantor = make_user(email="g@example.com", role=Role.GUARANTOR)

    assert "loans.apply" in permissions_for(borrower)
    assert "investments.make" not in permissions_for(borrower)
    assert "investments.make" in permissions_for(investor)
    assert "loans.apply" not in permissions_for(investor)
    assert "guarantees.respond" in permissions_for(guarantor)
    for user in (borrower, investor, guarantor):
        assert not any(p.startswith("admin.") for p in permissions_for(user))


def test_admin_levels_are_tiered(admins):
    support = permissions_for(admins["support"])
    ops = permissions_for(admins["operations"])
    finance = permissions_for(admins["finance"])
    superuser = permissions_for(admins["super"])

    assert "admin.users.view" in support and "admin.accounts.freeze" not in support
    assert "admin.loans.approve" in ops and "admin.withdrawals.approve" not in ops
    assert "admin.withdrawals.approve" in finance and "admin.loans.approve" not in finance
    assert ops | finance <= superuser
    assert "admin.config.manage" in superuser
    assert not any(p.startswith("wallet.") for p in superuser)


def test_admin_without_level_has_no_admin_permissions(make_user):
    user = make_user(email="nolevel@example.com", role=Role.ADMIN, admin_level=AdminLevel.NONE)
    assert not any(p.startswith("admin.") for p in permissions_for(user))


def test_frozen_account_loses_money_movement(make_user):
    investor = make_user(email="f@example.com", role=Role.INVESTOR, is_frozen=True)
    perms = permissions_for(investor)
    assert "wallet.withdraw" not in perms and "investments.make" not in perms
    assert "wallet.view_own" in perms and "marketplace.view" in perms


def test_me_and_login_include_permissions(api_client, borrower):
    body = login(api_client, borrower)
    assert "loans.apply" in body["user"]["permissions"]
    me = api_client.get("/api/v1/accounts/me/").json()
    assert me["permissions"] == sorted(me["permissions"])
    assert me["role_label"] == "Borrower"


# --- Profile ---------------------------------------------------------------

def test_user_can_update_own_name_and_it_is_audited(auth_client, borrower):
    res = auth_client.patch("/api/v1/accounts/me/", {"first_name": "Brenda", "last_name": "Wanjiru"}, format="json")
    assert res.status_code == 200
    assert res.json()["full_name"] == "Brenda Wanjiru"
    entry = AuditLog.objects.get(action="user.profile.updated")
    assert entry.actor == borrower and entry.after["last_name"] == "Wanjiru"


def test_profile_update_ignores_protected_fields(auth_client, borrower):
    auth_client.patch(
        "/api/v1/accounts/me/",
        {"first_name": "B", "role": "ADMIN", "admin_level": "SUPER", "is_frozen": True},
        format="json",
    )
    borrower.refresh_from_db()
    assert borrower.role == Role.BORROWER and borrower.admin_level == AdminLevel.NONE
    assert borrower.is_frozen is False


# --- Pricing ---------------------------------------------------------------

def test_pricing_brackets_cover_0_to_100(auth_client):
    body = auth_client.get("/api/v1/pricing/brackets/").json()
    scores = sorted(s for b in body["brackets"] for s in range(b["min_score"], b["max_score"] + 1))
    assert scores == list(range(0, 101))  # no gaps, no overlaps
    assert body["source"] == "initial_configuration"


def test_guarantor_cannot_view_pricing(api_client, make_user):
    login(api_client, make_user(email="g2@example.com", role=Role.GUARANTOR))
    assert api_client.get("/api/v1/pricing/brackets/").status_code == 403


# --- Admin API ---------------------------------------------------------------

def test_customers_cannot_use_admin_api(auth_client):
    for url in ("/api/v1/admin/overview/", "/api/v1/admin/users/", "/api/v1/admin/audit-logs/"):
        res = auth_client.get(url)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "permission_denied"


def test_support_can_list_and_filter_users(api_client, admins, make_user):
    make_user(email="inv@example.com", role=Role.INVESTOR, first_name="Ian")
    login(api_client, admins["support"])

    res = api_client.get("/api/v1/admin/users/", {"role": "INVESTOR"})
    assert res.status_code == 200
    assert [u["email"] for u in res.json()["results"]] == ["inv@example.com"]

    res = api_client.get("/api/v1/admin/users/", {"search": "ian"})
    assert res.json()["count"] == 1


def test_overview_counts_users(api_client, admins, borrower):
    login(api_client, admins["super"])
    body = api_client.get("/api/v1/admin/overview/").json()
    assert body["users_by_role"]["BORROWER"] == 1
    assert body["users_by_role"]["ADMIN"] == 4
    assert body["admins_by_level"]["FINANCE"] == 1


def test_support_cannot_freeze(api_client, admins, borrower):
    login(api_client, admins["support"])
    res = api_client.post(f"/api/v1/admin/users/{borrower.id}/freeze/", {"reason": "Suspicious deposits pattern"}, format="json")
    assert res.status_code == 403


def test_operations_can_freeze_and_unfreeze_customer_with_audit(api_client, admins, borrower):
    login(api_client, admins["operations"])
    url = f"/api/v1/admin/users/{borrower.id}"

    res = api_client.post(f"{url}/freeze/", {"reason": "Suspicious deposits pattern"}, format="json")
    assert res.status_code == 200 and res.json()["is_frozen"] is True

    again = api_client.post(f"{url}/freeze/", {"reason": "Suspicious deposits pattern"}, format="json")
    assert again.status_code == 422 and again.json()["error"]["code"] == "no_change"

    res = api_client.post(f"{url}/unfreeze/", {"reason": "Customer verified by phone"}, format="json")
    assert res.json()["is_frozen"] is False

    actions = list(AuditLog.objects.filter(entity_id=str(borrower.id)).values_list("action", flat=True))
    assert sorted(actions) == ["user.account.frozen", "user.account.unfrozen"]


def test_freeze_requires_a_reason(api_client, admins, borrower):
    login(api_client, admins["operations"])
    res = api_client.post(f"/api/v1/admin/users/{borrower.id}/freeze/", {"reason": "bad"}, format="json")
    assert res.status_code == 400 and "reason" in res.json()["error"]["details"]


def test_only_super_admin_can_freeze_admins(api_client, admins):
    login(api_client, admins["operations"])
    res = api_client.post(
        f"/api/v1/admin/users/{admins['finance'].id}/freeze/", {"reason": "Testing the safeguards"}, format="json"
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "admin_target"

    login(api_client, admins["super"])
    res = api_client.post(
        f"/api/v1/admin/users/{admins['finance'].id}/freeze/", {"reason": "Testing the safeguards"}, format="json"
    )
    assert res.status_code == 200


def test_cannot_freeze_yourself(api_client, admins):
    me = admins["super"]
    login(api_client, me)
    res = api_client.post(f"/api/v1/admin/users/{me.id}/freeze/", {"reason": "Testing the safeguards"}, format="json")
    assert res.status_code == 422 and res.json()["error"]["code"] == "self_action"


def test_audit_log_list_is_searchable(api_client, admins, borrower):
    login(api_client, admins["operations"])
    api_client.post(f"/api/v1/admin/users/{borrower.id}/freeze/", {"reason": "Chargeback investigation"}, format="json")
    res = api_client.get("/api/v1/admin/audit-logs/", {"search": "chargeback"})
    assert res.status_code == 200
    assert res.json()["results"][0]["actor_email"] == "ops@example.com"


# --- Web app shell -------------------------------------------------------------

def test_web_app_is_served_with_strict_csp(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b'id="app"' in res.content
    assert b"web/js/app.js" in res.content
    csp = res["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
