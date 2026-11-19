from django.conf import settings
from django.db import models
from django.db.models import Q


class EmploymentStatus(models.TextChoices):
    EMPLOYED = "EMPLOYED", "Employed"
    SELF_EMPLOYED = "SELF_EMPLOYED", "Self-employed"
    UNEMPLOYED = "UNEMPLOYED", "Unemployed"
    STUDENT = "STUDENT", "Student"
    RETIRED = "RETIRED", "Retired"


class BorrowerProfile(models.Model):
    """Details a borrower declares about themselves. Income is marked verified only by an administrator."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="borrower_profile"
    )
    date_of_birth = models.DateField(null=True, blank=True)
    county = models.CharField(max_length=60, blank=True)
    town = models.CharField(max_length=80, blank=True)
    employment_status = models.CharField(max_length=20, choices=EmploymentStatus.choices, blank=True)
    employer_name = models.CharField(max_length=150, blank=True)
    monthly_income = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    monthly_obligations = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Existing loan repayments, rent and other fixed monthly commitments.",
    )
    income_verified = models.BooleanField(default=False)
    income_verified_at = models.DateTimeField(null=True, blank=True)
    income_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(monthly_income__isnull=True) | Q(monthly_income__gte=0),
                name="borrower_income_not_negative",
            ),
            models.CheckConstraint(condition=Q(monthly_obligations__gte=0), name="borrower_obligations_not_negative"),
        ]

    def __str__(self):
        return f"Borrower profile of {self.user}"

    @property
    def is_complete(self):
        return bool(self.date_of_birth and self.county and self.employment_status and self.monthly_income is not None)
