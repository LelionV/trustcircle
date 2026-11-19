from django.apps import AppConfig


class AccountingConfig(AppConfig):
    """Immutable double-entry ledger, reversals, reconciliation."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    label = "accounting"
    verbose_name = "Accounting"
