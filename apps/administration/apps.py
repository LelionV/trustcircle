from django.apps import AppConfig


class AdministrationConfig(AppConfig):
    """Admin dashboards, configuration and permission levels."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.administration"
    label = "administration"
    verbose_name = "Administration"
