from django.contrib import admin

from .models import Guarantee, GuaranteeClaim


@admin.register(Guarantee)
class GuaranteeAdmin(admin.ModelAdmin):
    list_display = ("__str__",)


@admin.register(GuaranteeClaim)
class GuaranteeClaimAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

