"""One-time codes for email and phone verification."""
import uuid

from django.conf import settings
from django.db import models


class OtpChannel(models.TextChoices):
    EMAIL = "EMAIL", "Email"
    PHONE = "PHONE", "Phone"


class OneTimeCode(models.Model):
    """
    A short-lived verification code. Only a salted hash of the code is
    stored; the code itself is sent to the user and never kept.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="one_time_codes")
    channel = models.CharField(max_length=10, choices=OtpChannel.choices)
    destination = models.CharField(max_length=254, help_text="Email or phone the code was sent to.")
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "channel", "created_at"], name="otp_user_channel_idx")]

    def __str__(self):
        return f"{self.channel} code for {self.user_id}"
