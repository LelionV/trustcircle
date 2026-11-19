from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Shared base models, money utilities, errors, health check."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    label = "common"
    verbose_name = "Common"
