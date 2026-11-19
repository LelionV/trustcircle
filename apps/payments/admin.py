from django.contrib import admin

from apps.accounting.admin import ReadOnly

from .models import PaymentIntent


@admin.register(PaymentIntent)
class PaymentIntentAdmin(ReadOnly):
    """Read-only: a payment's status only changes through provider confirmation (never by hand)."""

    list_display = ("__str__", "user", "provider", "status", "created_at")
    list_filter = ("status", "direction", "provider")
    search_fields = ("user__email", "provider_reference")
