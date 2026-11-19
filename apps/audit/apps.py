from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Append-only audit trail for admin and financial actions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    label = "audit"
    verbose_name = "Audit"
