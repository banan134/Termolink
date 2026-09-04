"""E-mail backend that reads the SMTP configuration from the database (MailSettings), falling
back to the environment (SMTP_URL) or the console backend when nothing is configured."""

import logging
import time
from collections.abc import Sequence
from typing import Any

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend
from django.core.mail.message import EmailMessage

from . import crypto

log = logging.getLogger("termolink.mail")
CACHE_TTL_S = 30
_cache: dict[str, Any] = {"at": 0.0, "row": None}


def set_password(row: Any, password: str) -> None:
    row.password_enc = crypto.encrypt("mail", password.encode("utf-8")) if password else None


def get_password(row: Any) -> str:
    if not row.password_enc:
        return ""
    return crypto.decrypt("mail", bytes(row.password_enc)).decode("utf-8")


def current_settings(*, fresh: bool = False) -> Any | None:
    """MailSettings row when enabled, cached for 30 s (the worker sends alerts in a loop)."""
    from django.db import DatabaseError

    from .models import MailSettings

    now = time.monotonic()
    if not fresh and now - _cache["at"] < CACHE_TTL_S:
        return _cache["row"]
    try:
        with __import__("apps.tenants.context", fromlist=["system_context"]).system_context():
            row = MailSettings.objects.filter(pk=1, enabled=True).first()
    except DatabaseError:
        row = None
    _cache.update(at=now, row=row)
    return row


def invalidate() -> None:
    _cache["at"] = 0.0


def backend_for(row: Any | None, **kwargs: Any) -> BaseEmailBackend:
    if row is not None and row.host:
        return SmtpBackend(
            host=row.host,
            port=row.port,
            username=row.username or None,
            password=get_password(row) or None,
            use_tls=row.use_tls and not row.use_ssl,
            use_ssl=row.use_ssl,
            timeout=row.timeout_s,
            **kwargs,
        )
    if getattr(settings, "EMAIL_HOST", ""):
        return SmtpBackend(**kwargs)
    return ConsoleBackend(**kwargs)


class DatabaseEmailBackend(BaseEmailBackend):
    """Django EMAIL_BACKEND: delegates each send to the backend chosen at that moment."""

    def __init__(self, fail_silently: bool = False, **kwargs: Any) -> None:
        super().__init__(fail_silently=fail_silently, **kwargs)
        # send_mail() forwards auth_user/auth_password as username/password — the DB row wins
        self._kwargs = {k: v for k, v in kwargs.items() if k not in ("username", "password")}

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        row = current_settings()
        if row is not None and row.from_email:
            for m in email_messages:
                if not m.from_email or m.from_email == settings.DEFAULT_FROM_EMAIL:
                    m.from_email = row.from_email
        backend = backend_for(row, fail_silently=self.fail_silently, **self._kwargs)
        return int(backend.send_messages(list(email_messages)) or 0)
