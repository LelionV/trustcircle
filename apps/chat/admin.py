from django.contrib import admin

from .models import UserReport, Conversation


@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display = ("__str__",)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

