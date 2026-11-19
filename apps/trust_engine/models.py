"""
Trust score storage.

* TrustConfig     versioned scoring rules (weights, points, caps)
* TrustScore      the current score per borrower
* TrustEvent      append-only history: every change, with its reason
* RepaymentRecord / LoanOutcome / ExtensionRecord / ManualAdjustment
                  the facts the score is calculated from. Repayments,
                  completions and extensions are recorded by the repayment
                  engine (Phase 8) through apps.trust_engine.services.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.versioned import VersionedConfig, one_active_constraint, unique_version_constraint


class TrustConfig(VersionedConfig):
    class Meta(VersionedConfig.Meta):
        constraints = [
            one_active_constraint("trust_config_one_active"),
            unique_version_constraint("trust_config_unique_version"),
        ]


class Confidence(models.TextChoices):
    NEW = "NEW", "New borrower"
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class TrustScore(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="trust_score"
    )
    score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Empty until identity is verified.")
    previous_score = models.PositiveSmallIntegerField(null=True, blank=True)
    confidence = models.CharField(max_length=10, choices=Confidence.choices, default=Confidence.NEW)
    breakdown = models.JSONField(default=dict)
    installments_counted = models.PositiveIntegerField(default=0)
    early_payments = models.PositiveIntegerField(default=0)
    on_time_payments = models.PositiveIntegerField(default=0)
    late_payments = models.PositiveIntegerField(default=0)
    completed_loans = models.PositiveIntegerField(default=0)
    defaults = models.PositiveIntegerField(default=0)
    config = models.ForeignKey(TrustConfig, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    last_assessed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(score__isnull=True) | Q(score__lte=100), name="trust_score_max_100"),
        ]

    def __str__(self):
        return f"Trust {self.score} for {self.user}"


class TrustEventType(models.TextChoices):
    ASSESSMENT = "ASSESSMENT", "Score assessed"
    INSTALLMENT_PAID = "INSTALLMENT_PAID", "Installment paid"
    LOAN_COMPLETED = "LOAN_COMPLETED", "Loan completed"
    DEFAULT = "DEFAULT", "Loan defaulted"
    EXTENSION = "EXTENSION", "Repayment extension"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT", "Manual adjustment"
    RULES_CHANGED = "RULES_CHANGED", "Scoring rules changed"


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Trust history can't be edited.")

    def delete(self):
        raise PermissionError("Trust history can't be deleted.")


class TrustEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trust_events")
    event_type = models.CharField(max_length=24, choices=TrustEventType.choices)
    points = models.SmallIntegerField(null=True, blank=True, help_text="Points this event contributed, if any.")
    score_before = models.PositiveSmallIntegerField(null=True, blank=True)
    score_after = models.PositiveSmallIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=255)
    reference = models.CharField(max_length=64, blank=True)
    config = models.ForeignKey(TrustConfig, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Trust history can't be edited.")
        super().save(*args, **kwargs)

    @property
    def change(self):
        if self.score_before is None or self.score_after is None:
            return None
        return self.score_after - self.score_before


class RepaymentRecord(models.Model):
    """One scheduled installment, paid. Unique per installment, so it can only count once."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="repayment_records")
    loan_reference = models.CharField(max_length=64, db_index=True)
    installment_reference = models.CharField(max_length=64, unique=True)
    due_date = models.DateField()
    paid_on = models.DateField()
    amount_due = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2)
    days_early = models.IntegerField(help_text="Negative when late.")
    counted = models.BooleanField(help_text="False when below the minimum or not paid in full.")
    raw_points = models.SmallIntegerField()
    counted_points = models.SmallIntegerField()
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class LoanOutcome(models.Model):
    class Outcome(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        DEFAULTED = "DEFAULTED", "Defaulted"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="loan_outcomes")
    loan_reference = models.CharField(max_length=64, unique=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    days_early = models.IntegerField(default=0, help_text="Days before the final due date the loan was repaid.")
    bonus_points = models.PositiveSmallIntegerField(default=0)
    recorded_at = models.DateTimeField(auto_now_add=True)


class ExtensionRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extension_records")
    loan_reference = models.CharField(max_length=64, db_index=True)
    extension_reference = models.CharField(max_length=64, unique=True)
    after_missed_payment = models.BooleanField()
    penalty_points = models.PositiveSmallIntegerField()
    recorded_at = models.DateTimeField(auto_now_add=True)


class ManualAdjustment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trust_adjustments")
    points = models.SmallIntegerField()
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
