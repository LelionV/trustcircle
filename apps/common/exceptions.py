"""
Structured API errors.

Every error response has the same shape so the Flutter and web clients can
handle them in one place:

    {
      "error": {
        "code": "validation_error",
        "message": "Human readable summary.",
        "details": {...},          # field errors or extra context
        "request_id": "..."
      }
    }
"""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class BusinessRuleViolation(exceptions.APIException):
    """Raise from service code when a domain rule is broken."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "business_rule_violation"
    default_detail = "The request breaks a business rule."

    def __init__(self, detail=None, code=None, extra=None):
        super().__init__(detail=detail, code=code)
        self.extra = extra or {}


def _message_for(exc, data) -> str:
    if isinstance(exc, exceptions.ValidationError):
        return "One or more fields are invalid."
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return str(getattr(exc, "detail", exc))


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return _server_error(exc, context)

    code = getattr(exc, "default_code", "error")
    if isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        if isinstance(codes, str):
            code = codes

    data = response.data
    if isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
        details = data
    elif isinstance(exc, BusinessRuleViolation):
        details = exc.extra
    else:
        details = {}

    request = context.get("request")
    body = {
        "error": {
            "code": code,
            "message": _message_for(exc, data),
            "details": details,
            "request_id": getattr(request, "request_id", None) if request else None,
        }
    }
    return Response(body, status=response.status_code, headers=_retained_headers(response))


def _retained_headers(response):
    keep = ("WWW-Authenticate", "Retry-After", "Allow")
    return {h: response[h] for h in keep if h in response}


def _server_error(exc, context):
    """
    An unexpected error (a bug, a missing database table or column...). It is logged with its traceback
    and the request id. The client gets JSON in the usual shape so the app can show the reference; in
    DEBUG the message also names the error, so it can be fixed without digging through logs.
    """
    import logging

    from django.conf import settings
    from django.db import DatabaseError

    request = context.get("request")
    request_id = getattr(request, "request_id", None) if request else None
    logging.getLogger("apps.errors").exception(
        "Unhandled error on %s %s [%s]", getattr(request, "method", "?"), getattr(request, "path", "?"), request_id)
    if isinstance(exc, DatabaseError) and any(w in str(exc).lower() for w in ("unknown column", "doesn't exist",
                                                                             "no such table", "no such column")):
        message = ("The database is missing tables or columns for this version. Run "
                   "'python manage.py makemigrations' and 'python manage.py migrate', then try again.")
        code = "database_not_migrated"
    else:
        message = "Something went wrong on the server. Please try again; if it keeps happening, quote the reference."
        code = "server_error"
    if settings.DEBUG:
        message = f"{message} [{type(exc).__name__}: {str(exc)[:300]}]"
    body = {"error": {"code": code, "message": message, "details": {}, "request_id": request_id}}
    return Response(body, status=500)
