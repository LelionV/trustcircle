from django.conf import settings
from django.db import models


class SourceOfFunds(models.TextChoices):
    SALARY = "SALARY", "Salary"
    BUSINESS = "BUSINESS", "Business income"
    SAVINGS = "SAVINGS", "Savings"
    INVESTMENTS = "INVESTMENTS", "Other investments"
    PENSION = "PENSION", "Pension"
    OTHER = "OTHER", "Other"


class InvestorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="investor_profile"
    )
    date_of_birth = models.DateField(null=True, blank=True)
    county = models.CharField(max_length=60, blank=True)
    town = models.CharField(max_length=80, blank=True)
    occupation = models.CharField(max_length=120, blank=True)
    source_of_funds = models.CharField(max_length=20, choices=SourceOfFunds.choices, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Investor profile of {self.user}"

    @property
    def is_complete(self):
        return bool(self.date_of_birth and self.county and self.occupation and self.source_of_funds)
