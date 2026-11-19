from django.apps import AppConfig


class KycConfig(AppConfig):
    """Identity documents, verification workflow, secure document access."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.kyc"
    label = "kyc"
    verbose_name = "KYC"
