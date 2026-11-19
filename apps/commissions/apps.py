from django.apps import AppConfig


class CommissionsConfig(AppConfig):
    """Platform, guarantor and fee configuration and calculation."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.commissions"
    label = "commissions"
    verbose_name = "Commissions"
