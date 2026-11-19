from django.contrib import admin

from apps.accounting.admin import ReadOnly

from .models import Investment, LoanOffer


@admin.register(Investment)
class InvestmentAdmin(ReadOnly):
    list_display = ("__str__",)


@admin.register(LoanOffer)
class LoanOfferAdmin(ReadOnly):
    list_display = ("__str__",)

