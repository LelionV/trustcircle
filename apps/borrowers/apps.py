from django.apps import AppConfig


class BorrowersConfig(AppConfig):
    """Borrower profiles, income and employment information."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.borrowers"
    label = "borrowers"
    verbose_name = "Borrowers"
