"""
Versioned configuration. Settings are never edited in place: every change
creates a new version (who, when, why), the previous one is kept, and
exactly one version is active.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from .constraints import ConditionalUnique, flag_field


class VersionedConfig(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"active_flag": (lambda c: c.is_active, Q(is_active=True))}

    version = models.PositiveIntegerField()
    parameters = models.JSONField()
    is_active = models.BooleanField(default=False)
    active_flag = flag_field()
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-version"]

    def __str__(self):
        return f"{self.__class__.__name__} v{self.version}{' (active)' if self.is_active else ''}"

    @classmethod
    def active(cls, default_parameters):
        """The active version, creating version 1 from the defaults the first time."""
        current = cls.objects.filter(is_active=True).first()
        if current is None:
            current = cls.objects.create(
                version=1, parameters=default_parameters(), is_active=True, reason="Initial configuration"
            )
        return current

    @classmethod
    def publish(cls, *, parameters, actor, reason):
        """Deactivate the current version and activate a new one. Call inside a transaction."""
        latest = cls.objects.select_for_update().order_by("-version").first()
        cls.objects.filter(is_active=True).update(is_active=False, active_flag=None)
        return cls.objects.create(
            version=(latest.version + 1) if latest else 1,
            parameters=parameters,
            is_active=True,
            reason=reason,
            created_by=actor,
        )


def one_active_constraint(name):
    return models.UniqueConstraint(fields=["active_flag"], name=name)


def unique_version_constraint(name):
    return models.UniqueConstraint(fields=["version"], name=name)
