"""Terms acceptance gate, encrypted settings and payment webhook checks.

Run with:  python manage.py test tests.test_terms_and_gateways
"""
import hashlib
import hmac
import json

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role, User
from apps.common import crypto
from apps.legal import services as legal
from apps.platform_config.services import save_gateway

from .helpers import PASSWORD

TEST_KEY = Fernet.generate_key().decode()
TERMS_BODY = "These terms explain how the platform works, what you agree to, and how we handle your money. " * 2


@override_settings(FIELD_ENCRYPTION_KEY=TEST_KEY)
class TermsGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="terms.user@example.com", password=PASSWORD, role=Role.BORROWER)
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        legal.publish(None, title="Terms of use", body=TERMS_BODY)

    def test_api_is_blocked_until_terms_are_accepted(self):
        res = self.client.get("/api/v1/wallet/")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "terms_not_accepted")

    def test_profile_and_terms_stay_reachable_while_blocked(self):
        self.assertEqual(self.client.get("/api/v1/accounts/me/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/legal/current/").json()["accepted"], False)

    def test_accepting_unblocks_the_api(self):
        self.assertEqual(self.client.post("/api/v1/legal/accept/").status_code, 200)
        res = self.client.get("/api/v1/wallet/")
        self.assertNotEqual((res.json().get("error") or {}).get("code"), "terms_not_accepted")

    def test_a_new_version_must_be_accepted_again(self):
        self.client.post("/api/v1/legal/accept/")
        legal.publish(None, title="Terms of use", body=TERMS_BODY + " Updated clause.")
        res = self.client.get("/api/v1/wallet/")
        self.assertEqual(res.json()["error"]["code"], "terms_not_accepted")
        self.assertEqual(res.json()["error"]["details"]["terms_version"], 2)


class CryptoTests(TestCase):
    @override_settings(FIELD_ENCRYPTION_KEY=TEST_KEY)
    def test_secrets_round_trip_and_are_not_stored_as_plain_text(self):
        token = crypto.encrypt("sk_test_secret_123")
        self.assertNotIn("sk_test_secret_123", token)
        self.assertEqual(crypto.decrypt(token), "sk_test_secret_123")


@override_settings(FIELD_ENCRYPTION_KEY=TEST_KEY)
class PaystackWebhookTests(TestCase):
    url = "/api/v1/payments/webhooks/paystack/"

    def setUp(self):
        save_gateway("PAYSTACK", {"is_enabled": True, "secret_key": "sk_test_abc",
                                  "callback_base_url": "https://p2p.example.co.ke"}, actor=None)

    def _event(self):
        return json.dumps({"event": "charge.success", "data": {"reference": "NOT-OURS", "amount": 100000}}).encode()

    def test_unsigned_callbacks_are_rejected(self):
        res = self.client.post(self.url, data=self._event(), content_type="application/json",
                               HTTP_X_PAYSTACK_SIGNATURE="forged")
        self.assertEqual(res.status_code, 403)

    def test_signed_callback_for_unknown_payment_is_acknowledged_not_settled(self):
        body = self._event()
        signature = hmac.new(b"sk_test_abc", body, hashlib.sha512).hexdigest()
        res = self.client.post(self.url, data=body, content_type="application/json",
                               HTTP_X_PAYSTACK_SIGNATURE=signature)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ignored")
