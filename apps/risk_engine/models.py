import uuid

from django.conf import settings
from django.db import models

from apps.common.versioned import VersionedConfig, one_active_constraint, unique_version_constraint

from .calculators import CLASS_LABELS, CLASSES

RISK_CLASS_CHOICES = [(c, CLASS_LABELS[c]) for c in CLASSES]


class RiskConfig(VersionedConfig):
    class Meta(VersionedConfig.Meta):
        constraints = [
            one_active_constraint("risk_config_one_active"),
            unique_version_constraint("risk_config_unique_version"),
        ]


class RiskProfile(models.Model):
    """The current risk assessment for a user, plus any manual override."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="risk_profile"
    )
    score = models.PositiveSmallIntegerField()
    classification = models.CharField(max_length=10, choices=RISK_CLASS_CHOICES)
    factors = models.JSONField(default=list)
    config = models.ForeignKey(RiskConfig, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    assessed_at = models.DateTimeField()
    override_classification = models.CharField(max_length=10, choices=RISK_CLASS_CHOICES, blank=True)
    override_reason = models.TextField(blank=True)
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    override_at = models.DateTimeField(null=True, blank=True)

    @property
    def effective_classification(self):
        return self.override_classification or self.classification

    def __str__(self):
        return f"Risk {self.score} ({self.effective_classification}) for {self.user}"


class RiskAssessment(models.Model):
    """History: one row each time the score or classification changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_assessments")
    score = models.PositiveSmallIntegerField()
    classification = models.CharField(max_length=10, choices=RISK_CLASS_CHOICES)
    factors = models.JSONField(default=list)
    reason = models.CharField(max_length=255)
    config = models.ForeignKey(RiskConfig, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
