from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """Payment provider abstraction (M-Pesa, bank, sandbox)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    label = "payments"
    verbose_name = "Payments"
