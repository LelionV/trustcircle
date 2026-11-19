"""
Administration: disputes raised by customers. (Configuration lives with the
engine it configures; permissions in apps.accounts.permissions.)
"""
import uuid

from django.conf import settings
from django.db import models


class DisputeCategory(models.TextChoices):
    PAYMENT = "PAYMENT", "A payment or withdrawal"
    REPAYMENT = "REPAYMENT", "A loan repayment"
    DISTRIBUTION = "DISTRIBUTION", "Investment returns"
    FEES = "FEES", "Fees or charges"
    TRUST = "TRUST", "My trust score"
    OTHER = "OTHER", "Something else"


class DisputeStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "Being looked at"
    RESOLVED = "RESOLVED", "Resolved"
    REJECTED = "REJECTED", "Closed without change"


class Dispute(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True)
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="disputes")
    category = models.CharField(max_length=14, choices=DisputeCategory.choices)
    subject = models.CharField(max_length=120)
    description = models.TextField()
    loan = models.ForeignKey("loans.Loan", null=True, blank=True, on_delete=models.PROTECT, related_name="disputes")
    transaction_reference = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=12, choices=DisputeStatus.choices, default=DisputeStatus.OPEN,
                              db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} {self.subject}"
