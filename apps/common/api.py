"""Small helpers for API views that return hand-built dicts."""
import datetime
import uuid
from decimal import Decimal

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.response import Response

from .pagination import StandardPagination


def clean(value):
    """Decimals -> strings (never floats), recursively. Dates/UUIDs are left to the JSON renderer."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def ok(data, status=200):
    return Response(clean(data), status=status)


def paginated(view, request, queryset, row):
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request, view=view)
    return paginator.get_paginated_response(clean([row(x) for x in page]))


def csv_response(text, filename):
    resp = HttpResponse(text, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def validated(serializer_class, data):
    s = serializer_class(data=data)
    s.is_valid(raise_exception=True)
    return s.validated_data


class AmountField(serializers.DecimalField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("min_value", Decimal("0.01"))
        super().__init__(**kwargs)


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=1000)


class IdempotentInput(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")


__all__ = ["clean", "ok", "paginated", "csv_response", "validated", "AmountField", "ReasonInput",
           "IdempotentInput", "datetime", "uuid"]
