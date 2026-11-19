"""
Repayments, how each one was split, and loan extensions.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field


class Repayment(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"idempotency_flag": (lambda r: bool(r.idempotency_key), ~Q(idempotency_key=""))}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="repayments")
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="repayments_made")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    principal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    interest = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_interest = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    late_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    allocation = models.JSONField(default=list, help_text="Which installments this payment cleared.")
    entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.PROTECT, related_name="+")
    idempotency_key = models.CharField(max_length=80, blank=True)
    idempotency_flag = flag_field()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="repayment_amount_positive"),
            models.UniqueConstraint(fields=["loan", "idempotency_key", "idempotency_flag"],
                                    name="repayment_unique_idempotency_key"),
        ]


class ShareRole(models.TextChoices):
    INVESTOR = "INVESTOR", "Investor"
    GUARANTOR = "GUARANTOR", "Guarantor"
    PLATFORM = "PLATFORM", "Platform"


class DistributionLine(models.Model):
    """Who received what from one repayment (or recovery)."""

    repayment = models.ForeignKey(Repayment, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="distribution")
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="distribution_lines")
    role = models.CharField(max_length=10, choices=ShareRole.choices)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="distributions_received")
    investment = models.ForeignKey("investments.Investment", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="distributions")
    principal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    interest = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_interest = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    fees = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_recovery = models.BooleanField(default=False)
    entry = models.ForeignKey("accounting.JournalEntry", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def total(self):
        return self.principal + self.interest + self.extension_interest + self.fees


class ExtensionStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Waiting for review"
    AWAITING_CONSENT = "AWAITING_CONSENT", "Waiting for investors"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class ExtensionRequest(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"open_flag": (lambda e: e.status in ("REQUESTED", "AWAITING_CONSENT"),
                                        Q(status__in=["REQUESTED", "AWAITING_CONSENT"]))}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="extension_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    days = models.PositiveSmallIntegerField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=ExtensionStatus.choices, default=ExtensionStatus.REQUESTED,
                              db_index=True)
    open_flag = flag_field()
    remaining_principal = models.DecimalField(max_digits=14, decimal_places=2)
    extension_interest = models.DecimalField(max_digits=14, decimal_places=2)
    extension_fee = models.DecimalField(max_digits=14, decimal_places=2)
    after_missed_payment = models.BooleanField(default=False)
    rules_snapshot = models.JSONField(default=dict)
    consent_deadline = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["loan", "open_flag"], name="extension_one_open_per_loan"),
        ]

    @property
    def total_cost(self):
        return self.extension_interest + self.extension_fee


class ExtensionVote(models.Model):
    extension = models.ForeignKey(ExtensionRequest, on_delete=models.CASCADE, related_name="votes")
    investor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    agrees = models.BooleanField()
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["extension", "investor"], name="extension_vote_once"),
        ]
