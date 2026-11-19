"""
Payment provider abstraction.

    provider = get_provider("MPESA")
    ref = provider.start_collection(intent)   # e.g. M-Pesa STK push to the customer's phone
    ref = provider.start_payout(intent)       # e.g. M-Pesa B2C to the customer's phone

Confirmation always arrives separately (a provider callback, or the sandbox
"confirm" action in development) and is handled by
apps.payments.services.settle(). A provider call returning successfully only
means the request was accepted, never that money moved.

The M-Pesa provider follows Safaricom's Daraja API (STK Push for collections,
B2C for payouts). It is switched on with environment variables and must be
tested against the Daraja sandbox before use. See README, "M-Pesa".
"""
import base64
import json
import secrets
import urllib.request
from datetime import datetime

from django.conf import settings


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


class PaymentProvider:
    code = ""
    collects_automatically = False  # True when the provider calls us back on its own

    def start_collection(self, intent) -> str:
        raise NotImplementedError

    def start_payout(self, intent) -> str:
        raise NotImplementedError


class SandboxProvider(PaymentProvider):
    """Development only: payments stay pending until someone presses "Confirm (sandbox)"."""

    code = "SANDBOX"

    def _ref(self):
        return f"SBX-{secrets.token_hex(6).upper()}"

    def start_collection(self, intent):
        return self._ref()

    def start_payout(self, intent):
        return self._ref()


class MpesaProvider(PaymentProvider):
    code = "MPESA"
    collects_automatically = True

    def __init__(self):
        cfg = getattr(settings, "MPESA", {})
        required = ("CONSUMER_KEY", "CONSUMER_SECRET", "SHORTCODE", "PASSKEY", "CALLBACK_BASE_URL", "CALLBACK_TOKEN")
        if not all(cfg.get(k) for k in required):
            raise ProviderNotConfigured("M-Pesa isn't set up. Add the MPESA_* settings (see README).")
        self.cfg = cfg
        self.base = "https://sandbox.safaricom.co.ke" if cfg.get("ENVIRONMENT", "sandbox") == "sandbox" \
            else "https://api.safaricom.co.ke"

    def _token(self):
        creds = base64.b64encode(f"{self.cfg['CONSUMER_KEY']}:{self.cfg['CONSUMER_SECRET']}".encode()).decode()
        req = urllib.request.Request(f"{self.base}/oauth/v1/generate?grant_type=client_credentials",
                                     headers={"Authorization": f"Basic {creds}"})
        with urllib.request.urlopen(req, timeout=20) as res:  # noqa: S310 - fixed Safaricom host
            return json.loads(res.read())["access_token"]

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310
                return json.loads(res.read())
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"M-Pesa request failed: {exc}") from exc

    def _callback(self, name):
        return (f"{self.cfg['CALLBACK_BASE_URL'].rstrip('/')}/api/v1/payments/mpesa/{name}/"
                f"?token={self.cfg.get('CALLBACK_TOKEN', '')}")

    @staticmethod
    def _msisdn(phone):
        return phone.lstrip("+")

    def start_collection(self, intent):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{self.cfg['SHORTCODE']}{self.cfg['PASSKEY']}{ts}".encode()).decode()
        data = self._post("/mpesa/stkpush/v1/processrequest", {
            "BusinessShortCode": self.cfg["SHORTCODE"], "Password": password, "Timestamp": ts,
            "TransactionType": "CustomerPayBillOnline", "Amount": int(intent.amount),
            "PartyA": self._msisdn(intent.phone_number), "PartyB": self.cfg["SHORTCODE"],
            "PhoneNumber": self._msisdn(intent.phone_number),
            "CallBackURL": self._callback("callback"),
            "AccountReference": f"P2P{str(intent.pk)[:8]}", "TransactionDesc": "P2P Lend",
        })
        if str(data.get("ResponseCode")) != "0":
            raise ProviderError(data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa refused the request.")
        return data["CheckoutRequestID"]

    def start_payout(self, intent):
        for key in ("B2C_INITIATOR", "B2C_SECURITY_CREDENTIAL", "B2C_SHORTCODE"):
            if not self.cfg.get(key):
                raise ProviderNotConfigured("M-Pesa payouts need the MPESA_B2C_* settings.")
        data = self._post("/mpesa/b2c/v3/paymentrequest", {
            "OriginatorConversationID": str(intent.pk), "InitiatorName": self.cfg["B2C_INITIATOR"],
            "SecurityCredential": self.cfg["B2C_SECURITY_CREDENTIAL"], "CommandID": "BusinessPayment",
            "Amount": int(intent.amount), "PartyA": self.cfg["B2C_SHORTCODE"],
            "PartyB": self._msisdn(intent.phone_number), "Remarks": "P2P Lend withdrawal",
            "QueueTimeOutURL": self._callback("b2c-timeout"),
            "ResultURL": self._callback("b2c-result"),
            "Occasion": "Withdrawal",
        })
        if str(data.get("ResponseCode")) != "0":
            raise ProviderError(data.get("errorMessage") or "M-Pesa refused the payout.")
        return data["ConversationID"]

    @staticmethod
    def parse_stk_callback(body):
        """(provider_reference, succeeded, amount or None, message) from Daraja's STK callback JSON."""
        cb = body["Body"]["stkCallback"]
        amount = None
        for item in cb.get("CallbackMetadata", {}).get("Item", []):
            if item.get("Name") == "Amount":
                amount = item.get("Value")
        return cb["CheckoutRequestID"], int(cb["ResultCode"]) == 0, amount, cb.get("ResultDesc", "")

    @staticmethod
    def parse_b2c_result(body):
        r = body["Result"]
        return r["ConversationID"], int(r["ResultCode"]) == 0, r.get("ResultDesc", "")


def get_provider(code):
    if code == "SANDBOX":
        if not getattr(settings, "SANDBOX_PAYMENTS_ENABLED", False):
            raise ProviderNotConfigured("Sandbox payments are switched off on this server.")
        return SandboxProvider()
    if code == "MPESA":
        return MpesaProvider()
    if code in ("INTASEND", "PESAPAL", "PAYSTACK"):
        from .gateways import build_provider  # imported here: gateways.py builds on this module

        return build_provider(code)
    raise ProviderNotConfigured("Bank transfers aren't connected yet.")


def available_providers():
    """Providers a customer can use. 'payout' says whether withdrawals can go that way."""
    from .gateways import enabled_gateways

    result = []
    if getattr(settings, "SANDBOX_PAYMENTS_ENABLED", False):
        result.append({"code": "SANDBOX", "label": "Sandbox (testing, no real money)", "payout": True})
    try:
        MpesaProvider()
        result.append({"code": "MPESA", "label": "M-Pesa", "payout": True})
    except ProviderNotConfigured:
        pass
    result.extend(enabled_gateways())
    return result
