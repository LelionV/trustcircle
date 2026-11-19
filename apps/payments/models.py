"""
Payment intents: money coming in from, or going out to, M-Pesa, a bank or the
development sandbox. An intent only becomes money in a wallet once the
provider confirms it. Nothing is assumed to have succeeded.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field


class Provider(models.TextChoices):
    SANDBOX = "SANDBOX", "Sandbox (testing)"
    MPESA = "MPESA", "M-Pesa"
    BANK = "BANK", "Bank transfer"
    INTASEND = "INTASEND", "IntaSend"
    PESAPAL = "PESAPAL", "Pesapal"
    PAYSTACK = "PAYSTACK", "Paystack"


class Direction(models.TextChoices):
    IN = "IN", "Deposit"
    OUT = "OUT", "Withdrawal"


class Purpose(models.TextChoices):
    DEPOSIT = "DEPOSIT", "Deposit"
    REPAYMENT = "REPAYMENT", "Loan repayment"
    WITHDRAWAL = "WITHDRAWAL", "Withdrawal"


class IntentStatus(models.TextChoices):
    PENDING = "PENDING", "Waiting for confirmation"
    AWAITING_APPROVAL = "AWAITING_APPROVAL", "Waiting for approval"
    PROCESSING = "PROCESSING", "Being paid out"
    SUCCEEDED = "SUCCEEDED", "Completed"
    FAILED = "FAILED", "Failed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


FINAL_STATUSES = (IntentStatus.SUCCEEDED, IntentStatus.FAILED, IntentStatus.REJECTED, IntentStatus.CANCELLED)


class PaymentIntent(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"idempotency_flag": (lambda i: bool(i.idempotency_key), ~Q(idempotency_key=""))}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_intents")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    purpose = models.CharField(max_length=12, choices=Purpose.choices)
    provider = models.CharField(max_length=10, choices=Provider.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    phone_number = models.CharField(max_length=20, blank=True)
    loan = models.ForeignKey("loans.Loan", null=True, blank=True, on_delete=models.PROTECT, related_name="payment_intents")
    status = models.CharField(max_length=20, choices=IntentStatus.choices, default=IntentStatus.PENDING, db_index=True)
    provider_reference = models.CharField(max_length=80, null=True, blank=True, unique=True)
    checkout_url = models.URLField(max_length=500, blank=True,
                                   help_text="Where the customer finishes paying (card and checkout-page providers).")
    idempotency_key = models.CharField(max_length=80, blank=True)
    idempotency_flag = flag_field()
    request_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    settle_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    failure_reason = models.CharField(max_length=255, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="intent_amount_positive"),
            models.UniqueConstraint(fields=["user", "idempotency_key", "idempotency_flag"],
                                    name="intent_unique_idempotency_key"),
        ]

    def __str__(self):
        return f"{self.get_direction_display()} {self.amount} ({self.get_status_display()})"

    @property
    def is_final(self):
        return self.status in FINAL_STATUSES
