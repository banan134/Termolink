"""Local development (docker-compose.dev.yml)."""

from .base import *  # noqa: F403
from .base import _is_pytest, env

DEBUG = True
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "backend"])
_dev_port = env("DEV_HTTP_PORT", default="8080")
CSRF_TRUSTED_ORIGINS = [f"http://localhost:{_dev_port}", f"http://127.0.0.1:{_dev_port}"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Uncompressed static files: no collectstatic needed with runserver.
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

DEV_ADMIN_PASSWORD: str = env("DEV_ADMIN_PASSWORD", default="")
DEV_POLL_INTERVAL_S: int = 0 if _is_pytest else env.int("DEV_POLL_INTERVAL_S", default=600)
