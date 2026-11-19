from django.apps import AppConfig


class GuarantorsConfig(AppConfig):
    """Guarantee requests, acceptance, obligations and claims."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.guarantors"
    label = "guarantors"
    verbose_name = "Guarantors"
