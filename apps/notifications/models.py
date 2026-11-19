"""
In-app notifications (always), push via FCM when configured, and email for
the events that matter most.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field


class Notification(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"dedupe_flag": (lambda n: bool(n.dedupe_key), ~Q(dedupe_key=""))}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40, db_index=True)
    title = models.CharField(max_length=120)
    body = models.TextField()
    link = models.CharField(max_length=200, blank=True, help_text="Where the web app should open, e.g. #/wallet")
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=120, blank=True,
                                  help_text="Stops scheduled jobs sending the same reminder twice.")
    dedupe_flag = flag_field()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "dedupe_key", "dedupe_flag"], name="notification_unique_dedupe"),
        ]

    def __str__(self):
        return f"{self.user}: {self.title}"


class DeviceToken(models.Model):
    """A phone registered for push notifications (Flutter app, FCM)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=10, choices=[("android", "Android"), ("ios", "iOS"), ("web", "Web")])
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
