"""Know-your-customer submissions: identity documents and their review."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field
from apps.common.uploads import private_storage, random_path


def kyc_upload_to(instance, filename):
    return random_path("kyc", instance.user_id, filename)


class DocumentType(models.TextChoices):
    NATIONAL_ID = "NATIONAL_ID", "National ID"
    PASSPORT = "PASSPORT", "Passport"
    ALIEN_ID = "ALIEN_ID", "Alien ID"


class KycStatus(models.TextChoices):
    NOT_SUBMITTED = "NOT_SUBMITTED", "Not submitted"
    PENDING = "PENDING", "Waiting for review"
    APPROVED = "APPROVED", "Verified"
    REJECTED = "REJECTED", "Rejected"


class KycSubmission(ConditionalUnique, models.Model):
    FILE_FIELDS = ("id_front", "id_back", "selfie", "proof_of_income")
    CONDITIONAL_UNIQUE = {"pending_flag": (lambda k: k.status == "PENDING", Q(status="PENDING"))}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="kyc_submissions")
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    document_number = models.CharField(max_length=30, db_index=True)
    legal_first_name = models.CharField(max_length=150)
    legal_last_name = models.CharField(max_length=150)
    date_of_birth = models.DateField()
    nationality = models.CharField(max_length=60, default="Kenyan")
    pending_flag = flag_field()

    id_front = models.FileField(upload_to=kyc_upload_to, storage=private_storage)
    id_back = models.FileField(upload_to=kyc_upload_to, storage=private_storage, blank=True)
    selfie = models.FileField(upload_to=kyc_upload_to, storage=private_storage)
    proof_of_income = models.FileField(upload_to=kyc_upload_to, storage=private_storage, blank=True)

    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.label) for s in KycStatus if s != KycStatus.NOT_SUBMITTED],
        default=KycStatus.PENDING,
        db_index=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="kyc_reviews"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "pending_flag"], name="kyc_one_pending_submission_per_user"),
        ]

    def __str__(self):
        return f"KYC {self.get_status_display()} for {self.user}"


def kyc_status_for(user) -> str:
    """Status of the user's latest submission, or NOT_SUBMITTED."""
    latest = user.kyc_submissions.order_by("-submitted_at").values_list("status", flat=True).first()
    return latest or KycStatus.NOT_SUBMITTED
