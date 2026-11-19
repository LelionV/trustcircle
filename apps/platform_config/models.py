"""
Settings an administrator changes from the web app: which wallet providers are
switched on and their keys, and the TalkSasa SMS account. Secrets are stored
encrypted (apps.common.crypto) and are never sent back to the browser.
"""
from django.db import models

from apps.common.crypto import decrypt


class PaymentGateway(models.Model):
    class Code(models.TextChoices):
        INTASEND = "INTASEND", "IntaSend"
        PESAPAL = "PESAPAL", "Pesapal"
        PAYSTACK = "PAYSTACK", "Paystack"

    class Environment(models.TextChoices):
        SANDBOX = "SANDBOX", "Test (sandbox)"
        LIVE = "LIVE", "Live"

    code = models.CharField(max_length=12, choices=Code.choices, unique=True)
    is_enabled = models.BooleanField(default=False)
    environment = models.CharField(max_length=10, choices=Environment.choices, default=Environment.SANDBOX)
    public_key = models.CharField(max_length=255, blank=True,
                                  help_text="Publishable key. For Pesapal, the consumer key.")
    secret_key = models.TextField(blank=True, help_text="Encrypted at rest. For Pesapal, the consumer secret.")
    webhook_secret = models.TextField(blank=True,
                                      help_text="Encrypted at rest. For IntaSend, the webhook challenge.")
    callback_base_url = models.URLField(max_length=200, blank=True,
                                        help_text="Public address of this server, e.g. https://p2p.example.co.ke")
    extra = models.JSONField(default=dict, blank=True, help_text="Provider-generated values, e.g. Pesapal's IPN id.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.get_code_display()

    def secret(self) -> str:
        return decrypt(self.secret_key)

    def webhook(self) -> str:
        return decrypt(self.webhook_secret)

    @property
    def webhook_path(self) -> str:
        return f"/api/v1/payments/webhooks/{self.code.lower()}/"


class SmsGateway(models.Model):
    """A single row (pk=1): the TalkSasa account used for every SMS the platform sends."""

    is_enabled = models.BooleanField(default=False)
    base_url = models.URLField(max_length=200, default="https://bulksms.talksasa.com/api/v3/")
    sender_id = models.CharField(max_length=11, blank=True, help_text="Approved sender name, up to 11 characters.")
    api_key = models.TextField(blank=True, help_text="Encrypted at rest.")
    updated_at = models.DateTimeField(auto_now=True)

    def key(self) -> str:
        return decrypt(self.api_key)
