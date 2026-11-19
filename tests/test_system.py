import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_supports_row_locks_or_serialised_writes():
    # MySQL (InnoDB) gives row locks for select_for_update; the SQLite fallback serialises writes instead.
    if connection.vendor == "mysql":
        assert connection.features.has_select_for_update
        assert connection.settings_dict["OPTIONS"].get("charset") == "utf8mb4"
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.sql_mode")
            assert "STRICT_TRANS_TABLES" in cursor.fetchone()[0]
    else:
        assert connection.vendor == "sqlite"


@pytest.mark.django_db
def test_conditional_uniques_are_enforced_by_the_database(make_user):
    """The flag-column constraints must hold on MySQL too (partial unique indexes don't exist there)."""
    from django.db import IntegrityError, transaction

    from apps.notifications.models import Notification

    user = make_user(email="flags@example.com")
    Notification.objects.create(user=user, kind="x", title="t", body="b", dedupe_key="reminder-1")
    Notification.objects.create(user=user, kind="x", title="t", body="b")  # blank keys never collide
    Notification.objects.create(user=user, kind="x", title="t", body="b")
    with pytest.raises(IntegrityError), transaction.atomic():
        Notification.objects.create(user=user, kind="x", title="t", body="b", dedupe_key="reminder-1")


@pytest.mark.django_db
def test_health_reports_ok(api_client):
    response = api_client.get("/api/v1/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["currency"] == "KES"
    assert response.headers["X-Request-ID"]


@pytest.mark.django_db
def test_request_id_is_echoed(api_client):
    response = api_client.get("/api/v1/health/", HTTP_X_REQUEST_ID="flutter-abc12345")
    assert response.headers["X-Request-ID"] == "flutter-abc12345"


@pytest.mark.django_db
def test_openapi_schema_and_swagger_are_served(api_client):
    schema = api_client.get("/api/schema/")
    assert schema.status_code == 200
    assert b"/api/v1/auth/token/" in schema.content
    assert b"/api/v1/health/" in schema.content

    docs = api_client.get("/api/docs/")
    assert docs.status_code == 200


def test_celery_ping_runs_eagerly():
    from apps.common.tasks import ping

    assert ping.delay().get(timeout=5) == "pong"


@pytest.mark.django_db
def test_unknown_endpoint_returns_404(auth_client):
    response = auth_client.get("/api/v1/accounts/me/does-not-exist/")
    assert response.status_code == 404
