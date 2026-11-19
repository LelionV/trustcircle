"""
Deposits through IntaSend, Pesapal and Paystack. Keys and switches come from
the database (Configuration > Payments & SMS), not from .env.

Each provider only says a request was accepted. Money moves when the provider's
webhook arrives and the payment is verified, through payments.services.settle().
Pesapal's webhook carries no trusted result, so the server asks Pesapal for the
status of the order before settling.

Endpoints follow each provider's public API. Test them in the provider's
sandbox before going live (see the setup README).
"""
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal

from apps.common.exceptions import BusinessRuleViolation

from .providers import PaymentProvider, ProviderError, ProviderNotConfigured

log = logging.getLogger(__name__)

GATEWAY_CODES = ("INTASEND", "PESAPAL", "PAYSTACK")
LABELS = {
    "INTASEND": "M-Pesa or card (IntaSend)",
    "PESAPAL": "Card or mobile money (Pesapal)",
    "PAYSTACK": "Card or bank (Paystack)",
}


class WebhookRejected(Exception):
    pass


def new_reference(intent) -> str:
    """Our own reference for an intent. Unique, and at most 32 characters."""
    return f"P2P{uuid.uuid4().hex[:24].upper()}"


def _msisdn(phone: str) -> str:
    return phone.lstrip("+")


def _http(method, url, *, headers=None, payload=None, timeout=30):
    body = json.dumps(payload).encode() if payload is not None else None
    all_headers = {"Accept": "application/json"}
    if payload is not None:
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=all_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - fixed provider hosts
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ProviderError(f"The payment provider answered {exc.code}: {detail}") from exc
    except OSError as exc:
        raise ProviderError(f"Couldn't reach the payment provider: {exc}") from exc


def _enabled(code):
    from apps.platform_config.models import PaymentGateway
    from apps.platform_config.services import gateway_problems

    g = PaymentGateway.objects.filter(code=code).first()
    if g is None or not g.is_enabled or gateway_problems(g):
        raise ProviderNotConfigured(
            f"{LABELS.get(code, code)} isn't switched on. An administrator can set it up under Configuration > Payments & SMS.")
    return g


def enabled_gateways():
    """Providers an administrator has switched on, for the wallet's provider list."""
    from apps.platform_config.models import PaymentGateway

    out = []
    for g in PaymentGateway.objects.filter(is_enabled=True):
        if g.secret_key:
            out.append({"code": g.code, "label": LABELS[g.code], "payout": False})
    return out


def build_provider(code):
    g = _enabled(code)
    return {"INTASEND": IntaSendProvider, "PESAPAL": PesapalProvider, "PAYSTACK": PaystackProvider}[code](g)


# --- Providers ---------------------------------------------------------------------------

class IntaSendProvider(PaymentProvider):
    """M-Pesa STK push through IntaSend's collection API."""

    code = "INTASEND"
    collects_automatically = True

    def __init__(self, config):
        self.cfg = config
        host = "https://sandbox.intasend.com" if config.environment == "SANDBOX" else "https://payment.intasend.com"
        self.base = f"{host}/api/v1"

    def _auth(self):
        return {"Authorization": f"Bearer {self.cfg.secret()}"}

    def start_collection(self, intent):
        data = _http("POST", f"{self.base}/payment/mpesa-stk-push/", headers=self._auth(), payload={
            "amount": int(intent.amount),
            "phone_number": _msisdn(intent.phone_number),
            "api_ref": str(intent.pk),
            "currency": "KES",
        })
        invoice_id = (data.get("invoice") or {}).get("invoice_id") or data.get("id")
        if not invoice_id:
            raise ProviderError("IntaSend didn't return a payment reference.")
        return invoice_id

    def start_payout(self, intent):
        raise ProviderNotConfigured("Withdrawals to IntaSend aren't available yet. Withdraw by M-Pesa instead.")


class PesapalProvider(PaymentProvider):
    """Pesapal API 3.0: a checkout page for cards and mobile money."""

    code = "PESAPAL"
    collects_automatically = True

    def __init__(self, config):
        self.cfg = config
        if config.environment == "SANDBOX":
            self.base = "https://cybqa.pesapal.com/pesapalv3/api"
        else:
            self.base = "https://pay.pesapal.com/v3/api"

    def _token(self):
        data = _http("POST", f"{self.base}/Auth/RequestToken", payload={
            "consumer_key": self.cfg.public_key, "consumer_secret": self.cfg.secret()})
        if not data.get("token"):
            raise ProviderError(f"Pesapal refused the keys: {data.get('error') or data.get('message') or 'no token'}")
        return data["token"]

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _notification_id(self, token):
        """Register our IPN (instant payment notification) URL once and remember its id."""
        if self.cfg.extra.get("ipn_id"):
            return self.cfg.extra["ipn_id"]
        data = _http("POST", f"{self.base}/URLSetup/RegisterIPNUrl", headers=self._auth(token), payload={
            "url": self.cfg.callback_base_url.rstrip("/") + self.cfg.webhook_path,
            "ipn_notification_type": "GET",
        })
        ipn_id = data.get("ipn_id")
        if not ipn_id:
            raise ProviderError("Pesapal didn't return a notification id.")
        self.cfg.extra = {**self.cfg.extra, "ipn_id": ipn_id}
        self.cfg.save(update_fields=["extra", "updated_at"])
        return ipn_id

    def start_collection(self, intent):
        token = self._token()
        user = intent.user
        data = _http("POST", f"{self.base}/Transactions/SubmitOrderRequest", headers=self._auth(token), payload={
            "id": new_reference(intent),
            "currency": "KES",
            "amount": float(intent.amount),
            "description": "P2P Lend deposit",
            "callback_url": self.cfg.callback_base_url.rstrip("/") + "/#/wallet",
            "notification_id": self._notification_id(token),
            "billing_address": {
                "email_address": user.email,
                "phone_number": user.phone_number or "",
                "first_name": user.first_name or "Customer",
                "last_name": user.last_name or "P2P",
            },
        })
        tracking_id, redirect = data.get("order_tracking_id"), data.get("redirect_url")
        if not tracking_id or not redirect:
            raise ProviderError(f"Pesapal didn't accept the order: {data.get('error') or 'no checkout link'}")
        intent.checkout_url = redirect
        return tracking_id

    def start_payout(self, intent):
        raise ProviderNotConfigured("Pesapal can't pay out. Withdraw by M-Pesa instead.")

    def order_status(self, tracking_id):
        token = self._token()
        return _http("GET", f"{self.base}/Transactions/GetTransactionStatus?"
                     + urllib.parse.urlencode({"orderTrackingId": tracking_id}), headers=self._auth(token))


class PaystackProvider(PaymentProvider):
    """Paystack hosted checkout (cards, bank and mobile money where Paystack offers it)."""

    code = "PAYSTACK"
    collects_automatically = True
    base = "https://api.paystack.co"

    def __init__(self, config):
        self.cfg = config

    def start_collection(self, intent):
        reference = new_reference(intent)
        data = _http("POST", f"{self.base}/transaction/initialize",
                     headers={"Authorization": f"Bearer {self.cfg.secret()}"}, payload={
                         "email": intent.user.email,
                         "amount": int((intent.amount * 100).to_integral_value()),  # Paystack takes minor units
                         "currency": "KES",
                         "reference": reference,
                         "callback_url": self.cfg.callback_base_url.rstrip("/") + "/#/wallet",
                     })
        if not data.get("status") or not (data.get("data") or {}).get("authorization_url"):
            raise ProviderError(f"Paystack refused the payment: {data.get('message') or 'unknown error'}")
        intent.checkout_url = data["data"]["authorization_url"]
        return data["data"].get("reference") or reference

    def start_payout(self, intent):
        raise ProviderNotConfigured("Withdrawals to Paystack aren't available yet. Withdraw by M-Pesa instead.")


# --- Webhooks ------------------------------------------------------------------------------

def _amount(value):
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except Exception:  # noqa: BLE001
        return None


def handle_webhook(provider, request):
    """Verify a provider callback and settle the payment. Returns the JSON reply to send back."""
    from . import services

    if provider == "intasend":
        return _intasend(request, services)
    if provider == "pesapal":
        return _pesapal(request, services)
    if provider == "paystack":
        return _paystack(request, services)
    raise WebhookRejected("Unknown payment provider.")


def _settle(services, reference, *, succeeded, raw, message, amount=None):
    try:
        services.settle(reference, succeeded=succeeded, raw=raw, message=message, amount=amount)
        return {"status": "settled" if succeeded else "failed"}
    except BusinessRuleViolation:
        # Unknown reference: acknowledge so the provider stops retrying, and log it.
        log.warning("Webhook for unknown payment reference %s", reference)
        return {"status": "ignored"}


def _intasend(request, services):
    cfg = _enabled("INTASEND")
    payload = request.data if isinstance(request.data, dict) else {}
    expected = cfg.webhook()
    # IntaSend sends the challenge you chose in its dashboard with every callback.
    if not expected or not hmac.compare_digest(str(payload.get("challenge", "")), expected):
        raise WebhookRejected("The webhook challenge doesn't match.")
    reference = payload.get("invoice_id")
    if not reference:
        raise WebhookRejected("No invoice id in the callback.")
    state = str(payload.get("state", "")).upper()
    if state == "COMPLETE":
        return _settle(services, reference, succeeded=True, raw=payload, message="",
                       amount=_amount(payload.get("value")))
    if state in ("FAILED", "CANCELLED"):
        return _settle(services, reference, succeeded=False, raw=payload,
                       message=str(payload.get("failed_reason") or state.title()))
    return {"status": "ignored"}


def _pesapal(request, services):
    cfg = _enabled("PESAPAL")
    tracking_id = request.query_params.get("OrderTrackingId", "")
    merchant_ref = request.query_params.get("OrderMerchantReference", "")
    if not tracking_id:
        raise WebhookRejected("No order tracking id.")
    # Pesapal's notification carries no result; ask for the order's status directly.
    status = PesapalProvider(cfg).order_status(tracking_id)
    description = str(status.get("payment_status_description", ""))
    raw = {"tracking_id": tracking_id, "status": status}
    if description == "Completed":
        result = _settle(services, tracking_id, succeeded=True, raw=raw, message="",
                         amount=_amount(status.get("amount")))
    elif description in ("Failed", "Invalid", "Reversed"):
        result = _settle(services, tracking_id, succeeded=False, raw=raw, message=description)
    else:
        result = {"status": "pending"}
    return {"orderNotificationType": "IPNCHANGE", "orderTrackingId": tracking_id,
            "orderMerchantReference": merchant_ref, "status": 200, **result}


def _paystack(request, services):
    cfg = _enabled("PAYSTACK")
    raw_body = request.body
    signature = request.headers.get("x-paystack-signature", "")
    expected = hmac.new(cfg.secret().encode(), raw_body, hashlib.sha512).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise WebhookRejected("The signature doesn't match.")
    event = json.loads(raw_body or b"{}")
    data = event.get("data") or {}
    reference = data.get("reference")
    if not reference:
        raise WebhookRejected("No reference in the callback.")
    if event.get("event") == "charge.success":
        minor_units = _amount(data.get("amount"))  # Paystack reports amounts in cents
        amount = minor_units / 100 if minor_units is not None else None
        return _settle(services, reference, succeeded=True, raw=event, message="", amount=amount)
    if event.get("event") == "charge.failed":
        return _settle(services, reference, succeeded=False, raw=event,
                       message=str(data.get("gateway_response") or "The payment failed."))
    return {"status": "ignored"}
