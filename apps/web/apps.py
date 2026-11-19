from django.apps import AppConfig


class WebConfig(AppConfig):
    """Responsive web application (single page) served by Django."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.web"
    label = "web"
    verbose_name = "Web application"
