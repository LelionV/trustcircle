from __future__ import annotations

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from apps.common.middleware import get_request_id

from .models import AuditLog


def _json_safe(value: Any) -> Any:
    """Decimals, UUIDs and datetimes -> JSON-compatible values."""
    if value is None:
        return None
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _client_ip(request) -> str | None:
    if request is None:
        return None
    # Nginx sets X-Real-IP; never trust a client-supplied X-Forwarded-For chain blindly.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def record(
    *,
    action: str,
    entity_type: str,
    entity_id: Any,
    actor=None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str = "",
    request=None,
) -> AuditLog:
    """Write one immutable audit entry. Call inside the same DB transaction as the change."""
    if actor is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            actor = request.user
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=_json_safe(before),
        after=_json_safe(after),
        reason=reason,
        request_id=getattr(request, "request_id", "") or (get_request_id() if get_request_id() != "-" else ""),
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request is not None else ""),
    )
