from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import User


class PlatformUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "role")


class PlatformUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = PlatformUserChangeForm
    add_form = PlatformUserCreationForm

    ordering = ("-date_joined",)
    list_display = ("email", "full_name", "role", "admin_level", "is_active", "is_frozen", "date_joined")
    list_filter = ("role", "admin_level", "is_active", "is_frozen", "is_email_verified", "is_phone_verified")
    search_fields = ("email", "phone_number", "first_name", "last_name")
    readonly_fields = ("id", "date_joined", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "phone_number")}),
        ("Role", {"fields": ("role", "admin_level")}),
        ("Verification", {"fields": ("is_email_verified", "is_phone_verified")}),
        ("Status", {"fields": ("is_active", "is_frozen", "is_staff", "is_superuser")}),
        ("Django permissions", {"classes": ("collapse",), "fields": ("groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "role", "password1", "password2")}),
    )
