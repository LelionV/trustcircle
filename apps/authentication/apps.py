from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    """JWT login, refresh, logout; OTP in Phase 2."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authentication"
    label = "authentication"
    verbose_name = "Authentication"
