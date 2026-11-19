"""
Base settings shared by every environment.

All secrets and environment-specific values come from environment variables
(or a local `.env` file in development). Nothing sensitive is hardcoded.
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
    CELERY_TASK_ALWAYS_EAGER=(bool, False),
    USE_REDIS_CHANNEL_LAYER=(bool, False),
    JWT_ACCESS_MINUTES=(int, 15),
    JWT_REFRESH_DAYS=(int, 7),
)

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    environ.Env.read_env(str(_env_file))

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "channels",
]

# Modular monolith: one Django app per business capability.
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.authentication",
    "apps.kyc",
    "apps.borrowers",
    "apps.investors",
    "apps.guarantors",
    "apps.loans",
    "apps.investments",
    "apps.repayments",
    "apps.wallets",
    "apps.accounting",
    "apps.legal",
    "apps.platform_config",
    "apps.payments",
    "apps.commissions",
    "apps.risk_engine",
    "apps.trust_engine",
    "apps.notifications",
    "apps.administration",
    "apps.reports",
    "apps.audit",
    "apps.chat",
    "apps.web",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.RequestIdMiddleware",
    "apps.legal.middleware.TermsGateMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database — MySQL (8.0.11+, or MariaDB 10.5+).
# InnoDB gives real row locks, so money-moving code (select_for_update) is
# safe with several app workers. Set the DB_* values in .env.
# DB_ENGINE=sqlite falls back to backend/db.sqlite3 (handy for a quick look,
# or to read an old SQLite database when moving it to MySQL).
# DATABASE_URL, if set, overrides everything (e.g. mysql://user:pass@host:3306/p2plend).
# ---------------------------------------------------------------------------
DB_ENGINE = env("DB_ENGINE", default="mysql").lower()
if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", default="p2plend"),
            "USER": env("DB_USER", default="p2plend"),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "HOST": env("DB_HOST", default="127.0.0.1"),
            "PORT": env("DB_PORT", default="3306"),
            "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
            "OPTIONS": {
                "charset": "utf8mb4",
                # Strict mode: MySQL refuses bad data instead of silently truncating it.
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
                "isolation_level": "read committed",
            },
            "TEST": {"NAME": env("DB_TEST_NAME", default="test_p2plend"), "CHARSET": "utf8mb4",
                     "COLLATION": "utf8mb4_unicode_ci"},
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")),
            "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
        }
    }
else:
    raise RuntimeError("DB_ENGINE must be 'mysql' or 'sqlite'.")
if env("DATABASE_URL", default=""):
    DATABASES["default"] = env.db("DATABASE_URL")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
# KYC documents will live in a private storage location (Phase 2) and are
# never served directly from MEDIA_URL.
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# Cache & Redis
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
# Rate limiting and idempotency keys live in the cache, so production must
# use Redis. In local development you can start without Redis.
if env.bool("USE_REDIS_CACHE", default=True):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# ---------------------------------------------------------------------------
# Channels (real-time)
# ---------------------------------------------------------------------------
if env("USE_REDIS_CHANNEL_LAYER"):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "240/minute",
        "auth": "10/minute",
        "otp": "10/hour",
        "chat": "60/minute",
    },
    # Monetary values are serialised as strings to avoid float rounding
    # on clients.
    "COERCE_DECIMAL_TO_STRING": True,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env("JWT_ACCESS_MINUTES")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("JWT_REFRESH_DAYS")),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "P2P Lending & Investment Platform API",
    "DESCRIPTION": (
        "Single API consumed by the Flutter mobile app and the web frontend. "
        "All financial calculations happen on the server; monetary values are "
        "decimal strings in KES unless stated otherwise."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------
PLATFORM_CURRENCY = env("PLATFORM_CURRENCY", default="KES")
MONEY_DECIMAL_PLACES = 2

# One-time codes for email/phone verification
OTP_LENGTH = 6
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_PER_HOUR = 5
# SMS delivery: "console" prints the message in the server log (development).
# A real gateway (e.g. Africa's Talking) plugs in at apps.authentication.sms.
SMS_BACKEND = env("SMS_BACKEND", default="console")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="P2P Lend <no-reply@p2plend.local>")

# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
# The sandbox provider lets you test deposits and withdrawals with no real
# money: each payment waits until you press "Confirm" (as if you had entered
# your M-Pesa PIN). Never enable it on a server handling real money.
SANDBOX_PAYMENTS_ENABLED = env.bool("SANDBOX_PAYMENTS_ENABLED", default=False)
MPESA = {
    "ENVIRONMENT": env("MPESA_ENVIRONMENT", default="sandbox"),  # sandbox | production
    "CONSUMER_KEY": env("MPESA_CONSUMER_KEY", default=""),
    "CONSUMER_SECRET": env("MPESA_CONSUMER_SECRET", default=""),
    "SHORTCODE": env("MPESA_SHORTCODE", default=""),
    "PASSKEY": env("MPESA_PASSKEY", default=""),
    "CALLBACK_BASE_URL": env("MPESA_CALLBACK_BASE_URL", default=""),
    "CALLBACK_TOKEN": env("MPESA_CALLBACK_TOKEN", default=""),
    "B2C_SHORTCODE": env("MPESA_B2C_SHORTCODE", default=""),
    "B2C_INITIATOR": env("MPESA_B2C_INITIATOR", default=""),
    "B2C_SECURITY_CREDENTIAL": env("MPESA_B2C_SECURITY_CREDENTIAL", default=""),
}

# Push notifications (Firebase Cloud Messaging). Empty = in-app only.
FCM_CREDENTIALS_FILE = env("FCM_CREDENTIALS_FILE", default="")

# Encrypts payment and SMS keys stored in the database. Required before saving any key.
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")
# Email copies of important notifications (deposits, withdrawals, defaults...)
NOTIFICATION_EMAILS = env.bool("NOTIFICATION_EMAILS", default=False)

# KYC and loan documents
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_ALLOWED_TYPES = ("image/jpeg", "image/png", "application/pdf")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        },
    },
    "filters": {
        "request_id": {"()": "apps.common.middleware.RequestIdLogFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "apps": {"level": "INFO"},
    },
}
