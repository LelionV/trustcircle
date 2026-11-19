from django.apps import AppConfig


class RepaymentsConfig(AppConfig):
    """Schedules, installments, payment allocation, distributions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.repayments"
    label = "repayments"
    verbose_name = "Repayments"
