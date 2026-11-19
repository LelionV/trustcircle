import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

HealthResponse = inline_serializer(
    name="HealthResponse",
    fields={
        "status": serializers.ChoiceField(choices=["ok", "degraded", "down"]),
        "time": serializers.DateTimeField(),
        "api_version": serializers.CharField(),
        "currency": serializers.CharField(),
        "checks": serializers.DictField(),
    },
)


class HealthView(APIView):
    """
    Liveness/readiness probe. The Flutter app calls this on start-up to
    confirm it can reach the backend.

    * database unavailable -> 503 "down"
    * cache/Redis unavailable -> 200 "degraded" (API still usable)
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    @extend_schema(responses={200: HealthResponse, 503: HealthResponse}, tags=["system"])
    def get(self, request):
        checks = {"database": self._check_database(), "cache": self._check_cache()}

        if checks["database"]["status"] != "ok":
            overall, http_status = "down", status.HTTP_503_SERVICE_UNAVAILABLE
        elif checks["cache"]["status"] != "ok":
            overall, http_status = "degraded", status.HTTP_200_OK
        else:
            overall, http_status = "ok", status.HTTP_200_OK

        return Response(
            {
                "status": overall,
                "time": timezone.now(),
                "api_version": "v1",
                "currency": settings.PLATFORM_CURRENCY,
                "checks": checks,
            },
            status=http_status,
        )

    @staticmethod
    def _check_database() -> dict:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return {"status": "ok", "vendor": connection.vendor}
        except Exception:  # noqa: BLE001 - health checks must never raise
            logger.exception("Database health check failed")
            return {"status": "error", "vendor": connection.vendor}

    @staticmethod
    def _check_cache() -> dict:
        try:
            cache.set("health:ping", "pong", timeout=5)
            ok = cache.get("health:ping") == "pong"
            return {"status": "ok" if ok else "error"}
        except Exception:  # noqa: BLE001
            logger.warning("Cache health check failed", exc_info=True)
            return {"status": "error"}
