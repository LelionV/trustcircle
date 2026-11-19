from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Custom user model, roles and admin permission levels."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"
