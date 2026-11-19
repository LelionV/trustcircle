"""Saving gateway and SMS settings. Every change is written to the audit trail, without secret values."""
from django.db import transaction

from apps.audit import services as audit
from apps.common.crypto import encrypt
from apps.common.exceptions import BusinessRuleViolation

from .models import PaymentGateway, SmsGateway

GATEWAY_NOTES = {
    "INTASEND": "Collects deposits by M-Pesa STK push and card. Copy the secret key from the IntaSend dashboard "
                "and choose a webhook challenge; enter the same challenge in IntaSend's webhook settings.",
    "PESAPAL": "Collects deposits on Pesapal's checkout page (cards and mobile money). Needs the consumer key and "
               "secret, and the public address of this server so Pesapal can call back.",
    "PAYSTACK": "Collects deposits on Paystack's checkout page. Needs the secret key, which Paystack also uses to "
                "sign webhooks, and the public address of this server.",
}


def gateway_rows():
    """All three providers, saved or not, in a stable order."""
    saved = {g.code: g for g in PaymentGateway.objects.all()}
    return [saved.get(code) or PaymentGateway(code=code) for code in PaymentGateway.Code.values]


def gateway_problems(g):
    problems = []
    if not g.secret_key:
        problems.append("the secret key is missing")
    if g.code == PaymentGateway.Code.PESAPAL and not g.public_key:
        problems.append("the consumer key is missing")
    if g.code == PaymentGateway.Code.INTASEND and not g.webhook_secret:
        problems.append("the webhook challenge is missing")
    if g.code in (PaymentGateway.Code.PESAPAL, PaymentGateway.Code.PAYSTACK) and not g.callback_base_url:
        problems.append("the public address of this server is missing")
    return problems


def _gateway_snapshot(g):
    return {"is_enabled": g.is_enabled, "environment": g.environment, "public_key": g.public_key,
            "callback_base_url": g.callback_base_url, "secret_set": bool(g.secret_key),
            "webhook_secret_set": bool(g.webhook_secret)}


@transaction.atomic
def save_gateway(code, data, *, actor, request=None):
    if code not in PaymentGateway.Code.values:
        raise BusinessRuleViolation("Unknown payment provider.", code="unknown_gateway")
    g = PaymentGateway.objects.select_for_update().filter(code=code).first() or PaymentGateway(code=code)
    before = _gateway_snapshot(g)
    for name in ("environment", "public_key", "callback_base_url"):
        if name in data:
            setattr(g, name, data[name])
    # A blank secret means "keep the one already saved".
    if data.get("secret_key"):
        g.secret_key = encrypt(data["secret_key"])
    if data.get("webhook_secret"):
        g.webhook_secret = encrypt(data["webhook_secret"])
    if "is_enabled" in data:
        g.is_enabled = data["is_enabled"]
    problems = gateway_problems(g)
    if g.is_enabled and problems:
        raise BusinessRuleViolation(
            "Can't switch this provider on yet: " + "; ".join(problems) + ".", code="incomplete_settings")
    g.save()
    audit.record(action="config.gateway_updated", entity_type="PaymentGateway", entity_id=g.pk, actor=actor,
                 before=before, after=_gateway_snapshot(g), request=request)
    return g


def sms_settings():
    obj, _ = SmsGateway.objects.get_or_create(pk=1)
    return obj


@transaction.atomic
def save_sms(data, *, actor, request=None):
    s = SmsGateway.objects.select_for_update().get_or_create(pk=1)[0]
    before = {"is_enabled": s.is_enabled, "base_url": s.base_url, "sender_id": s.sender_id, "api_key_set": bool(s.api_key)}
    for name in ("base_url", "sender_id"):
        if name in data:
            setattr(s, name, data[name])
    if data.get("api_key"):
        s.api_key = encrypt(data["api_key"])
    if "is_enabled" in data:
        s.is_enabled = data["is_enabled"]
    if s.is_enabled and (not s.api_key or not s.sender_id):
        raise BusinessRuleViolation("Can't switch SMS on yet: the API key and sender ID are needed.",
                                    code="incomplete_settings")
    s.save()
    audit.record(action="config.sms_updated", entity_type="SmsGateway", entity_id=s.pk, actor=actor, before=before,
                 after={"is_enabled": s.is_enabled, "base_url": s.base_url, "sender_id": s.sender_id,
                        "api_key_set": bool(s.api_key)}, request=request)
    return s


def active_sms():
    """The SMS account to use, or None when SMS is switched off or unfinished."""
    s = SmsGateway.objects.filter(pk=1, is_enabled=True).first()
    return s if s and s.api_key and s.sender_id else None
