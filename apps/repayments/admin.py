from django.contrib import admin

from apps.accounting.admin import ReadOnly

from .models import Repayment, ExtensionRequest


@admin.register(Repayment)
class RepaymentAdmin(ReadOnly):
    list_display = ("__str__",)


@admin.register(ExtensionRequest)
class ExtensionRequestAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

