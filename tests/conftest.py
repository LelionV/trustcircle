import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Role, User

PASSWORD = "Str0ng-Test-Pass!"


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache; isolate tests from each other.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(email="user@example.com", role=Role.BORROWER, **extra):
        return User.objects.create_user(email=email, password=PASSWORD, role=role, **extra)

    return _make


@pytest.fixture
def borrower(make_user):
    return make_user(email="borrower@example.com", role=Role.BORROWER)


@pytest.fixture
def auth_client(api_client, borrower):
    response = api_client.post(
        "/api/v1/auth/token/", {"email": borrower.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200, response.content
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    api_client.refresh_token = response.json()["refresh"]
    return api_client
