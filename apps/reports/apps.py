from django.apps import AppConfig


class ReportsConfig(AppConfig):
    """Financial and operational reporting."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    label = "reports"
    verbose_name = "Reports"
