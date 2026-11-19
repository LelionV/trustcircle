from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """In-app, push (FCM) and email notifications."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notifications"
