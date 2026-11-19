"""
Terms and conditions. Administrators publish a new version; every user must
accept the active version before they can use the platform. Each acceptance
is recorded with the time, IP address and browser, so the platform can show
which version a person agreed to.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class TermsDocument(models.Model):
    version = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=200)
    body = models.TextField(help_text="Plain text. Blank lines start new paragraphs.")
    is_active = models.BooleanField(default=False, db_index=True,
                                    help_text="Only one version is active; publishing switches the old one off.")
    published_at = models.DateTimeField(default=timezone.now)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-version"]

    def __str__(self):
        return f"Terms v{self.version}: {self.title}"


class TermsAcceptance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="terms_acceptances")
    terms = models.ForeignKey(TermsDocument, on_delete=models.PROTECT, related_name="acceptances")
    accepted_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-accepted_at"]
        # MySQL has no partial unique indexes, so one acceptance per user and version is a plain unique pair.
        constraints = [
            models.UniqueConstraint(fields=["user", "terms"], name="terms_one_acceptance_per_version"),
        ]
