import pytest

from apps.accounts.models import Role

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_login_returns_tokens_and_profile(api_client, borrower):
    response = api_client.post(
        "/api/v1/auth/token/", {"email": borrower.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access"] and body["refresh"]
    assert body["user"]["email"] == borrower.email
    assert body["user"]["role"] == Role.BORROWER


def test_login_is_case_insensitive_on_email(api_client, borrower):
    response = api_client.post(
        "/api/v1/auth/token/", {"email": "  BORROWER@Example.com ", "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200


def test_bad_credentials_return_structured_error(api_client, borrower):
    response = api_client.post(
        "/api/v1/auth/token/", {"email": borrower.email, "password": "wrong"}, format="json"
    )
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "no_active_account"
    assert error["message"] == "Invalid email or password."
    assert error["request_id"]


def test_missing_fields_return_validation_error(api_client):
    response = api_client.post("/api/v1/auth/token/", {}, format="json")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "email" in error["details"] and "password" in error["details"]


def test_me_requires_authentication(api_client):
    response = api_client.get("/api/v1/accounts/me/")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_returns_current_user(auth_client, borrower):
    response = auth_client.get("/api/v1/accounts/me/")
    assert response.status_code == 200
    assert response.json()["id"] == str(borrower.id)


def test_refresh_rotates_and_blacklists_old_token(api_client, auth_client):
    old_refresh = auth_client.refresh_token
    first = api_client.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh}, format="json")
    assert first.status_code == 200
    assert first.json()["refresh"] != old_refresh

    reused = api_client.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh}, format="json")
    assert reused.status_code == 401


def test_logout_blacklists_refresh_token(api_client, auth_client):
    refresh = auth_client.refresh_token
    response = auth_client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json")
    assert response.status_code == 205

    reuse = api_client.post("/api/v1/auth/token/refresh/", {"refresh": refresh}, format="json")
    assert reuse.status_code == 401


def test_cannot_logout_another_users_token(api_client, auth_client, make_user):
    other = make_user(email="other@example.com")
    other_login = api_client.post(
        "/api/v1/auth/token/", {"email": other.email, "password": PASSWORD}, format="json"
    ).json()
    response = auth_client.post("/api/v1/auth/logout/", {"refresh": other_login["refresh"]}, format="json")
    assert response.status_code == 400


def test_inactive_user_cannot_log_in(api_client, make_user):
    user = make_user(email="inactive@example.com", is_active=False)
    response = api_client.post(
        "/api/v1/auth/token/", {"email": user.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 401
