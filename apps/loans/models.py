"""
Loans: interest brackets, loan products, applications and their schedules.

A loan's pricing (trust score, risk, bracket, rate, method) is copied onto
the loan when it is submitted and again when it is approved. From approval
on, those terms are locked: a later change in the borrower's score or in
the bracket table never changes an existing loan. Only a formally approved
restructuring or extension (Phase 8) may create new terms.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field
from apps.common.uploads import private_storage, random_path


# --- Interest brackets -------------------------------------------------------------

class InterestBracketSet(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"active_flag": (lambda s: s.is_active, Q(is_active=True))}

    version = models.PositiveIntegerField(unique=True)
    is_active = models.BooleanField(default=False)
    active_flag = flag_field()
    # How the bracket rates are read: MONTHLY (% per month, the default for new tables), ANNUAL or PER_LOAN.
    # Empty means ANNUAL: tables created before this setting existed keep their original meaning.
    rate_basis = models.CharField(max_length=10, blank=True, default="")
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["active_flag"], name="bracket_set_one_active"),
        ]

    def __str__(self):
        return f"Interest brackets v{self.version}{' (active)' if self.is_active else ''}"

    @property
    def basis(self):
        return self.rate_basis or "ANNUAL"


class InterestBracket(models.Model):
    bracket_set = models.ForeignKey(InterestBracketSet, on_delete=models.CASCADE, related_name="brackets")
    min_score = models.PositiveSmallIntegerField()
    max_score = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=40)
    annual_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Empty means the rate is set manually."
    )

    class Meta:
        ordering = ["min_score"]
        constraints = [
            models.UniqueConstraint(fields=["bracket_set", "min_score"], name="bracket_unique_start"),
            models.CheckConstraint(condition=Q(max_score__gte=models.F("min_score")), name="bracket_range_valid"),
            models.CheckConstraint(condition=Q(max_score__lte=100), name="bracket_max_100"),
        ]

    def as_row(self):
        return {"min_score": self.min_score, "max_score": self.max_score, "label": self.label,
                "annual_rate": self.annual_rate}


# --- Products ----------------------------------------------------------------------

class InterestMethod(models.TextChoices):
    FLAT = "FLAT", "Flat"
    REDUCING_BALANCE = "REDUCING_BALANCE", "Reducing balance"


class RateBasis(models.TextChoices):
    ANNUAL = "ANNUAL", "Per year"
    MONTHLY = "MONTHLY", "Per month"
    PER_LOAN = "PER_LOAN", "Per loan"


class Frequency(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly"
    BIWEEKLY = "BIWEEKLY", "Every two weeks"
    MONTHLY = "MONTHLY", "Monthly"


class LoanProduct(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    min_amount = models.DecimalField(max_digits=14, decimal_places=2)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2)
    min_term_months = models.PositiveSmallIntegerField(default=1)
    max_term_months = models.PositiveSmallIntegerField(default=12)
    frequencies = models.JSONField(default=list, help_text="Allowed repayment frequencies.")
    interest_method = models.CharField(max_length=20, choices=InterestMethod.choices,
                                       default=InterestMethod.REDUCING_BALANCE)
    rate_basis = models.CharField(max_length=10, choices=RateBasis.choices, default=RateBasis.ANNUAL)
    requires_guarantor = models.BooleanField(default=True)
    funding_period_days = models.PositiveSmallIntegerField(default=14)
    max_installment_share = models.DecimalField(
        max_digits=5, decimal_places=2, default=50,
        help_text="Largest share (%) of monthly income left after commitments that repayments may take.",
    )
    max_open_loans = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(min_amount__gt=0), name="product_min_amount_positive"),
            models.CheckConstraint(condition=Q(max_amount__gte=models.F("min_amount")), name="product_amount_range"),
            models.CheckConstraint(condition=Q(min_term_months__gte=1), name="product_min_term"),
            models.CheckConstraint(condition=Q(max_term_months__gte=models.F("min_term_months")),
                                   name="product_term_range"),
        ]

    def __str__(self):
        return self.name


# --- Loans -------------------------------------------------------------------------

class LoanStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    APPROVED = "APPROVED", "Approved"
    PUBLISHED = "PUBLISHED", "Open for funding"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED", "Partly funded"
    FULLY_FUNDED = "FULLY_FUNDED", "Fully funded"
    GUARANTOR_PENDING = "GUARANTOR_PENDING", "Waiting for guarantor"
    READY_FOR_DISBURSEMENT = "READY_FOR_DISBURSEMENT", "Ready to pay out"
    DISBURSED = "DISBURSED", "Paid out"
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Repaid"
    OVERDUE = "OVERDUE", "Overdue"
    DEFAULTED = "DEFAULTED", "Defaulted"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"
    RESTRUCTURED = "RESTRUCTURED", "Restructured"


# Loans that are still a commitment for the borrower (used for limits and risk).
OPEN_LOAN_STATUSES = (
    LoanStatus.APPROVED, LoanStatus.PUBLISHED, LoanStatus.PARTIALLY_FUNDED, LoanStatus.FULLY_FUNDED,
    LoanStatus.GUARANTOR_PENDING, LoanStatus.READY_FOR_DISBURSEMENT, LoanStatus.DISBURSED,
    LoanStatus.ACTIVE, LoanStatus.OVERDUE, LoanStatus.RESTRUCTURED,
)
IN_REVIEW_STATUSES = (LoanStatus.SUBMITTED, LoanStatus.UNDER_REVIEW)
EDITABLE_STATUSES = (LoanStatus.DRAFT,)
MARKETPLACE_STATUSES = (LoanStatus.PUBLISHED, LoanStatus.PARTIALLY_FUNDED)


class LoanPurpose(models.TextChoices):
    BUSINESS = "BUSINESS", "Business"
    EDUCATION = "EDUCATION", "Education"
    MEDICAL = "MEDICAL", "Medical"
    HOME = "HOME", "Home improvement"
    AGRICULTURE = "AGRICULTURE", "Farming"
    EMERGENCY = "EMERGENCY", "Emergency"
    PERSONAL = "PERSONAL", "Personal"
    OTHER = "OTHER", "Other"


class FundingMode(models.TextChoices):
    STANDARD = "STANDARD", "Guaranteed (bracket rate)"
    OFFERS = "OFFERS", "Open offers (no guarantor)"


class Loan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True)
    borrower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loans")
    product = models.ForeignKey(LoanProduct, on_delete=models.PROTECT, related_name="loans")
    status = models.CharField(max_length=24, choices=LoanStatus.choices, default=LoanStatus.DRAFT, db_index=True)

    # What the borrower asked for
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    term_months = models.PositiveSmallIntegerField()
    repayment_frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    purpose = models.CharField(max_length=20, choices=LoanPurpose.choices)
    purpose_details = models.TextField(blank=True)
    employment_status = models.CharField(max_length=20, blank=True)
    monthly_income = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    monthly_obligations = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    proposed_guarantor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="guarantee_requests"
    )
    # STANDARD: guaranteed, priced from the bracket table. OFFERS: no guarantor; investors offer their own rate
    # and the final rate is the amount-weighted average of the offers the borrower accepts.
    funding_mode = models.CharField(max_length=10, choices=FundingMode.choices, default=FundingMode.STANDARD)

    # Pricing snapshot (taken at submission, refreshed and locked at approval)
    trust_score_snapshot = models.PositiveSmallIntegerField(null=True, blank=True)
    trust_confidence_snapshot = models.CharField(max_length=10, blank=True)
    risk_score_snapshot = models.PositiveSmallIntegerField(null=True, blank=True)
    risk_class_snapshot = models.CharField(max_length=10, blank=True)
    bracket_set = models.ForeignKey(InterestBracketSet, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    bracket_label = models.CharField(max_length=40, blank=True)
    # The loan's interest rate, read according to rate_basis (MONTHLY = % per month). The field keeps its
    # original name for compatibility; it is not necessarily a yearly rate.
    annual_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    interest_method = models.CharField(max_length=20, choices=InterestMethod.choices, blank=True)
    rate_basis = models.CharField(max_length=10, choices=RateBasis.choices, blank=True)
    requires_manual_pricing = models.BooleanField(default=False)
    installment_count = models.PositiveSmallIntegerField(null=True, blank=True)
    installment_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_interest = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_repayable = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    terms_locked_at = models.DateTimeField(null=True, blank=True)

    # Workflow
    submitted_at = models.DateTimeField(null=True, blank=True)
    review_started_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    funding_expires_at = models.DateTimeField(null=True, blank=True)
    funded_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Phases 5-8: funding, disbursement and the life of the loan
    fully_funded_at = models.DateTimeField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    overdue_since = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    defaulted_at = models.DateTimeField(null=True, blank=True)
    extension_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="loan_amount_positive"),
            models.CheckConstraint(condition=Q(term_months__gte=1), name="loan_term_positive"),
            models.CheckConstraint(condition=Q(funded_amount__gte=0) & Q(funded_amount__lte=models.F("amount")),
                                   name="loan_no_overfunding"),
        ]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"

    @property
    def terms_locked(self):
        return self.terms_locked_at is not None


class LoanStatusChange(models.Model):
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="+")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class InstallmentStatus(models.TextChoices):
    UPCOMING = "UPCOMING", "Upcoming"
    DUE = "DUE", "Due"
    PAID_EARLY = "PAID_EARLY", "Paid early"
    PAID_ON_TIME = "PAID_ON_TIME", "Paid on time"
    PAID_LATE = "PAID_LATE", "Paid late"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partly paid"
    OVERDUE = "OVERDUE", "Overdue"
    DEFAULTED = "DEFAULTED", "Defaulted"


PAID_STATUSES = (InstallmentStatus.PAID_EARLY, InstallmentStatus.PAID_ON_TIME, InstallmentStatus.PAID_LATE)
INSTALLMENT_COMPONENTS = ("late_fee", "extension_fee", "extension_interest", "interest", "principal")


class LoanInstallment(models.Model):
    """
    The locked repayment schedule, created when a loan is approved and
    re-dated from the disbursement date. Each component tracks what is due
    and what has been paid; payments clear components in the order in
    apps.repayments.calculators.COMPONENTS.
    """

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="installments")
    sequence = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    original_due_date = models.DateField(null=True, blank=True)
    principal = models.DecimalField(max_digits=14, decimal_places=2)
    interest = models.DecimalField(max_digits=14, decimal_places=2)
    fees = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    late_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_interest = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    principal_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    interest_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    late_fee_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_fee_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extension_interest_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=InstallmentStatus.choices, default=InstallmentStatus.UPCOMING)

    def due(self, component):
        return getattr(self, component) - getattr(self, f"{component}_paid")

    @property
    def amount_due(self):
        return sum((getattr(self, c) for c in INSTALLMENT_COMPONENTS), 0)

    @property
    def outstanding(self):
        return sum((self.due(c) for c in INSTALLMENT_COMPONENTS), 0)

    @property
    def is_paid(self):
        return self.status in PAID_STATUSES

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["loan", "sequence"], name="installment_unique_sequence"),
        ]


def loan_document_upload_to(instance, filename):
    return random_path("loans", instance.loan_id, filename)


class LoanDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=loan_document_upload_to, storage=private_storage)
    description = models.CharField(max_length=120)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]


class LoanAgreement(models.Model):
    """
    The terms the borrower accepts before money is paid out. A new version is
    created when an approved extension changes the terms; old versions stay.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="agreements")
    version = models.PositiveSmallIntegerField()
    terms = models.JSONField()
    text = models.TextField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["loan", "version"], name="agreement_unique_version"),
        ]

    def __str__(self):
        return f"Agreement v{self.version} for {self.loan.reference}"
