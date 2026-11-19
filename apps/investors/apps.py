from django.apps import AppConfig


class InvestorsConfig(AppConfig):
    """Investor profiles, preferences and statements."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.investors"
    label = "investors"
    verbose_name = "Investors"
