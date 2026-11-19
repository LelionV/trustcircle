from django.apps import AppConfig


class LoansConfig(AppConfig):
    """Loan products, applications, approval, agreements, extensions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.loans"
    label = "loans"
    verbose_name = "Loans"
