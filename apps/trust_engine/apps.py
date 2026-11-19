from django.apps import AppConfig


class TrustEngineConfig(AppConfig):
    """Trust score (0-100), history and explanations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.trust_engine"
    label = "trust_engine"
    verbose_name = "Trust engine"
