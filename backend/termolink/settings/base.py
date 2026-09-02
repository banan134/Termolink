"""Base settings shared by all environments. Everything configurable comes from env (12-factor)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

DJANGO_ENV: str = env("DJANGO_ENV", default="dev")
SECRET_KEY: str = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost"])
DEBUG = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.tenants",
    "apps.accounts",
]

AUTH_USER_MODEL = "accounts.User"
# auth.E003 wants unique=True on USERNAME_FIELD; we enforce UNIQUE (lower(email)) instead (docs/03).
SILENCED_SYSTEM_CHECKS = ["auth.E003"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "termolink.urls"
WSGI_APPLICATION = "termolink.wsgi.application"
ASGI_APPLICATION = "termolink.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

# --- Database: PostgreSQL 16 + TimescaleDB; one transaction per request (docs/03, RLS) ---
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = 60
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth / sessions (docs/08) ---
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "tl_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 7 * 24 * 3600  # hard max 7 days; idle timeout handled in stage 1 task 5
CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_HTTPONLY = False  # frontend reads it to send X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"

# --- REST framework / OpenAPI (docs/04) ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Termolink API",
    "VERSION": "1.0.0",
    "DESCRIPTION": "REST API portalu Termolink (docs/04-backend-api.md).",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
}

# --- i18n / time (UTC in DB, Europe/Warsaw in UI) ---
LANGUAGE_CODE = "pl"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static / media ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- E-mail ---
_smtp = env("SMTP_URL", default="")
if _smtp:
    EMAIL_CONFIG = env.email_url("SMTP_URL")
    vars().update(EMAIL_CONFIG)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "Termolink <noreply@termolink.local>"

# --- Termolink-specific configuration (docs/11 .env.example) ---
TOKEN_MASTER_KEY: str = env("TOKEN_MASTER_KEY", default="")
VIESSMANN_CLIENT_ID: str = env("VIESSMANN_CLIENT_ID", default="")
VIESSMANN_API_BASE: str = env(
    "VIESSMANN_API_BASE", default="https://api.viessmann-climatesolutions.com/iot/v1"
)
VIESSMANN_IAM_BASE: str = env(
    "VIESSMANN_IAM_BASE", default="https://iam.viessmann-climatesolutions.com/idp/v3"
)
VIESSMANN_MOCK: bool = env.bool("VIESSMANN_MOCK", default=False)
OAUTH_REDIRECT_BASE: str = env("OAUTH_REDIRECT_BASE", default="http://localhost:8080")
_raw_retention = env("RAW_RETENTION_DAYS", default="").strip()
RAW_RETENTION_DAYS: int | None = int(_raw_retention) if _raw_retention else None
ALERT_EMAIL_OPERATOR: str = env("ALERT_EMAIL_OPERATOR", default="")
SENSITIVE_COMMANDS: list[str] = env.list(
    "SENSITIVE_COMMANDS", default=["setMode", "setSchedule", "setCurve", "deactivate"]
)

# --- Logging: structured-ish to stdout; secrets never logged (docs/08) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="INFO")},
}
