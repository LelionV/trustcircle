from django.apps import AppConfig


class RiskEngineConfig(AppConfig):
    """Risk score (0-100) and classification."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.risk_engine"
    label = "risk_engine"
    verbose_name = "Risk engine"
