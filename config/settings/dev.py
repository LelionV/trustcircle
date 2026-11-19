"""Local development settings (Windows or Linux)."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env("DJANGO_DEBUG", default=True)

# Allow the Android emulator (10.0.2.2) and devices on your LAN to reach
# `manage.py runserver 0.0.0.0:8000`.
# Add your PC's LAN IP to DJANGO_ALLOWED_HOSTS in .env to test on a phone.
ALLOWED_HOSTS = sorted(set(ALLOWED_HOSTS) | {"localhost", "127.0.0.1", "192.168.100.9"})  # noqa: F405

# Flutter web / local web frontends run on random ports in development.
CORS_ALLOW_ALL_ORIGINS = True

# Browsable API is handy while developing.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = (  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Test payments with no real money (see README, "Wallet and payments").
SANDBOX_PAYMENTS_ENABLED = env.bool("SANDBOX_PAYMENTS_ENABLED", default=True)
