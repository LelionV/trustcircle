import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.borrowers.models import EmploymentStatus
from apps.common.constraints import ConditionalUnique, flag_field


class GuarantorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="guarantor_profile"
    )
    date_of_birth = models.DateField(null=True, blank=True)
    county = models.CharField(max_length=60, blank=True)
    town = models.CharField(max_length=80, blank=True)
    employment_status = models.CharField(max_length=20, choices=EmploymentStatus.choices, blank=True)
    employer_name = models.CharField(max_length=150, blank=True)
    monthly_income = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    income_verified = models.BooleanField(default=False)
    income_verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(monthly_income__isnull=True) | Q(monthly_income__gte=0),
                name="guarantor_income_not_negative",
            ),
        ]

    def __str__(self):
        return f"Guarantor profile of {self.user}"

    @property
    def is_complete(self):
        return bool(self.date_of_birth and self.county and self.employment_status and self.monthly_income is not None)


class GuaranteeStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Waiting for a reply"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    RELEASED = "RELEASED", "Released (loan repaid or cancelled)"
    CLAIMED = "CLAIMED", "Called on (loan defaulted)"


LIVE_GUARANTEE_STATUSES = (GuaranteeStatus.REQUESTED, GuaranteeStatus.ACCEPTED)


class Guarantee(ConditionalUnique, models.Model):
    """
    A guarantor's promise to cover a loan if it defaults. Requested when the
    loan opens for funding. A declined guarantee can be replaced by the
    borrower nominating someone else (a new Guarantee row).
    """

    CONDITIONAL_UNIQUE = {"live_flag": (lambda g: g.status in ("REQUESTED", "ACCEPTED", "CLAIMED"),
                                        Q(status__in=["REQUESTED", "ACCEPTED", "CLAIMED"]))}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="guarantees")
    live_flag = flag_field()
    guarantor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="guarantees")
    status = models.CharField(max_length=10, choices=GuaranteeStatus.choices, default=GuaranteeStatus.REQUESTED,
                              db_index=True)
    coverage_amount = models.DecimalField(max_digits=14, decimal_places=2)
    responded_at = models.DateTimeField(null=True, blank=True)
    response_note = models.CharField(max_length=255, blank=True)
    commission_earned = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # The borrower's total interest, locked in the guarantor's wallet from acceptance until the borrower has
    # paid the interest in full (or the guarantee ends). Used first if the loan defaults.
    locked_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lock_released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["loan", "live_flag"], name="guarantee_one_live_per_loan"),
        ]

    def __str__(self):
        return f"{self.guarantor} for {self.loan.reference} ({self.get_status_display()})"


class ClaimStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    PARTLY_RECOVERED = "PARTLY_RECOVERED", "Partly recovered"
    RECOVERED = "RECOVERED", "Recovered"
    WRITTEN_OFF = "WRITTEN_OFF", "Written off"


class GuaranteeClaim(models.Model):
    """What a defaulted loan's guarantor owes investors, and how much has been collected."""

    guarantee = models.OneToOneField(Guarantee, on_delete=models.PROTECT, related_name="claim")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    recovered = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reimbursed = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Paid back to the guarantor from later borrower repayments.")
    status = models.CharField(max_length=16, choices=ClaimStatus.choices, default=ClaimStatus.OPEN)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(recovered__lte=models.F("amount")), name="claim_not_over_recovered"),
        ]

    @property
    def outstanding(self):
        return self.amount - self.recovered
