"""Settings for the automated test suite (pytest)."""
import os
from pathlib import Path

import environ

# Values in backend/.env win; the defaults below only apply when neither the
# shell nor .env provides them. Tests run on the same MySQL server as the app:
# Django creates a separate database (test_p2plend) and drops it afterwards,
# so your data is never touched. The MySQL user needs rights on test_p2plend
# (see README). For a quick run without MySQL: set TEST_DB_ENGINE=sqlite.
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    environ.Env.read_env(str(_env_file))

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-production")

from .base import *  # noqa: E402,F401,F403
from .base import env  # noqa: E402

if env("TEST_DB_ENGINE", default="") == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# No Redis needed to run the test suite.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Verification codes are captured instead of sent; uploads go to a temp folder.
SMS_BACKEND = "locmem"
import tempfile  # noqa: E402

PRIVATE_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="p2plend-test-private-"))
MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="p2plend-test-media-"))

SANDBOX_PAYMENTS_ENABLED = True
NOTIFICATION_EMAILS = True
