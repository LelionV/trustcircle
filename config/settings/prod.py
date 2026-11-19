"""Production settings (Ubuntu + Nginx + Gunicorn/Uvicorn)."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")
if "RedisCache" not in CACHES["default"]["BACKEND"]:  # noqa: F405
    raise RuntimeError("Production requires Redis (USE_REDIS_CACHE=True) for shared rate limits.")
if CELERY_TASK_ALWAYS_EAGER:  # noqa: F405
    raise RuntimeError("CELERY_TASK_ALWAYS_EAGER must be False in production.")

# HTTPS is terminated at Nginx.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)

# Sandbox payments move no real money and must never be on in production.
if SANDBOX_PAYMENTS_ENABLED and not env.bool("ALLOW_SANDBOX_IN_PRODUCTION", default=False):  # noqa: F405
    raise RuntimeError("SANDBOX_PAYMENTS_ENABLED must be False in production.")
