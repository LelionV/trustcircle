"""
Pooled funding. Each investor's contribution to a loan is one Investment.
Money committed to a loan sits in the investor's escrow balance until the
loan is paid out (or the funding round fails and it is returned).

Distributions use each investment's *outstanding* principal:
    amount - principal_repaid - recovered
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field


class InvestmentStatus(models.TextChoices):
    COMMITTED = "COMMITTED", "Committed (waiting for the loan to fill)"
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Repaid"
    DEFAULTED = "DEFAULTED", "In default"
    REFUNDED = "REFUNDED", "Returned"


class Investment(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"idempotency_flag": (lambda i: bool(i.idempotency_key), ~Q(idempotency_key=""))}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="investments")
    investor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="investments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # The rate this investor lends at (same basis as the loan). For guaranteed loans it's the loan's rate;
    # for open-offer loans it's the rate the investor offered. Interest is shared by amount x rate.
    rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=12, choices=InvestmentStatus.choices, default=InvestmentStatus.COMMITTED,
                              db_index=True)
    principal_repaid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    interest_earned = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_interest_earned = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    recovered = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                    help_text="Principal returned from a guarantor or other recovery after default.")
    commit_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    idempotency_key = models.CharField(max_length=80, blank=True)
    idempotency_flag = flag_field()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="investment_amount_positive"),
            models.CheckConstraint(
                condition=Q(principal_repaid__gte=0) & Q(recovered__gte=0),
                name="investment_repaid_not_negative"),
            models.UniqueConstraint(fields=["investor", "idempotency_key", "idempotency_flag"],
                                    name="investment_unique_idempotency_key"),
        ]

    def __str__(self):
        return f"{self.investor} -> {self.loan.reference}: {self.amount}"

    @property
    def outstanding(self):
        if self.status in (InvestmentStatus.COMMITTED, InvestmentStatus.REFUNDED):
            return Decimal("0.00")
        return self.amount - self.principal_repaid - self.recovered

    @property
    def total_earned(self):
        return self.interest_earned + self.extension_interest_earned

    @property
    def share_percent(self):
        return (self.amount * 100 / self.loan.amount).quantize(Decimal("0.01"))


class OfferStatus(models.TextChoices):
    OPEN = "OPEN", "Waiting for the borrower"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    EXPIRED = "EXPIRED", "Expired"


class LoanOffer(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"open_flag": (lambda o: o.status == "OPEN", Q(status="OPEN"))}

    """
    An investor's offer on an open-offers loan (no guarantor): how much they'll
    lend and at what rate. The money is held in the investor's escrow while
    the offer is open, so an accepted offer can never bounce.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="offers")
    investor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loan_offers")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    message = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=OfferStatus.choices, default=OfferStatus.OPEN, db_index=True)
    open_flag = flag_field()
    hold_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    investment = models.OneToOneField(Investment, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="offer")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rate", "-amount", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="offer_amount_positive"),
            models.CheckConstraint(condition=Q(rate__gte=0), name="offer_rate_not_negative"),
            models.UniqueConstraint(fields=["loan", "investor", "open_flag"], name="offer_one_open_per_investor"),
        ]

    def __str__(self):
        return f"{self.investor} offers {self.amount} at {self.rate}% on {self.loan.reference}"
