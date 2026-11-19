from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.api import ok
from apps.common.permissions import HasPlatformPermission

from . import services
from .models import TermsDocument


def terms_row(t):
    return {"version": t.version, "title": t.title, "body": t.body, "published_at": t.published_at}


class CurrentTermsView(APIView):
    """The active terms and whether the signed-in user has accepted them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["legal"])
    def get(self, request):
        status = services.acceptance_status(request.user)
        terms = status["terms"]
        return ok({"accepted": status["accepted"], "terms": terms_row(terms) if terms else None})


class AcceptTermsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["legal"])
    def post(self, request):
        terms = services.accept(
            request.user,
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return ok({"accepted": True, "version": terms.version})


class PublishTermsSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(min_length=50, max_length=200000)


class AdminTermsView(APIView):
    """Administrators: list versions with acceptance counts, or publish a new version."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(tags=["configuration"])
    def get(self, request):
        rows = TermsDocument.objects.annotate(accepted_count=Count("acceptances")).order_by("-version")[:100]
        return ok([{**terms_row(t), "is_active": t.is_active, "accepted_count": t.accepted_count} for t in rows])

    @extend_schema(tags=["configuration"], request=PublishTermsSerializer)
    def post(self, request):
        serializer = PublishTermsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        terms = services.publish(request.user, request=request, **serializer.validated_data)
        return ok(terms_row(terms), status=201)
