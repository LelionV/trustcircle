"""
Administrator screens for wallet providers and SMS. Requires admin.config.manage
(super administrators). Secret values are write-only: the API only reports
whether they are set.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import ok
from apps.common.exceptions import BusinessRuleViolation
from apps.common.permissions import HasPlatformPermission

from . import services
from .models import PaymentGateway
from .talksasa import send_bulk


class GatewaySettingsSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    environment = serializers.ChoiceField(choices=PaymentGateway.Environment.choices, required=False)
    public_key = serializers.CharField(max_length=255, required=False, allow_blank=True)
    callback_base_url = serializers.URLField(max_length=200, required=False, allow_blank=True)
    secret_key = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)
    webhook_secret = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)


class SmsSettingsSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    base_url = serializers.URLField(max_length=200, required=False)
    sender_id = serializers.CharField(max_length=11, required=False, allow_blank=True)
    api_key = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)


class SmsTestSerializer(serializers.Serializer):
    phones = serializers.ListField(child=serializers.CharField(max_length=20), min_length=1, max_length=50)
    message = serializers.CharField(max_length=480)


def gateway_out(g):
    return {
        "code": g.code, "label": g.get_code_display(), "is_enabled": g.is_enabled,
        "environment": g.environment, "public_key": g.public_key, "callback_base_url": g.callback_base_url,
        "secret_set": bool(g.secret_key), "webhook_secret_set": bool(g.webhook_secret),
        "webhook_url": (g.callback_base_url.rstrip("/") + g.webhook_path) if g.callback_base_url else "",
        "note": services.GATEWAY_NOTES[g.code], "problems": services.gateway_problems(g),
    }


def sms_out(s):
    return {"is_enabled": s.is_enabled, "base_url": s.base_url, "sender_id": s.sender_id,
            "api_key_set": bool(s.api_key)}


class IntegrationsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(tags=["configuration"])
    def get(self, request):
        return ok({
            "gateways": [gateway_out(g) for g in services.gateway_rows()],
            "sms": sms_out(services.sms_settings()),
        })


class GatewayView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(tags=["configuration"], request=GatewaySettingsSerializer)
    def put(self, request, code):
        serializer = GatewaySettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        g = services.save_gateway(code, serializer.validated_data, actor=request.user, request=request)
        return ok(gateway_out(g))


class SmsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(tags=["configuration"], request=SmsSettingsSerializer)
    def put(self, request):
        serializer = SmsSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        s = services.save_sms(serializer.validated_data, actor=request.user, request=request)
        return ok(sms_out(s))


class SmsTestView(APIView):
    """Sends one message to each number listed, through the saved TalkSasa account."""

    permission_classes = [HasPlatformPermission]
    required_permission = "admin.config.manage"

    @extend_schema(tags=["configuration"], request=SmsTestSerializer)
    def post(self, request):
        serializer = SmsTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cfg = services.active_sms()
        if cfg is None:
            raise BusinessRuleViolation("Switch SMS on and save the API key and sender ID first.", code="sms_off")
        return ok(send_bulk(cfg, serializer.validated_data["phones"], serializer.validated_data["message"]))
