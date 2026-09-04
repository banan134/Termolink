"""Operator-configurable SMTP (2026-09-04): stored encrypted, used by the mail backend, testable."""

from typing import Any

import pytest
from django.core import mail as django_mail
from django.test import Client

from apps.accounts.models import Role, User
from apps.core import mail
from apps.core.models import MailSettings
from apps.tenants.context import SYSTEM, set_context

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)
    mail.invalidate()


def _login(user: User) -> Client:
    c = Client()
    user.totp_enabled = False
    user.save(update_fields=["totp_enabled"])
    r = c.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    return c


@pytest.mark.django_db
def test_settings_roundtrip_password_hidden_and_encrypted() -> None:
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    assert _login(tech).get("/api/v1/admin/settings/mail").status_code == 403
    c = _login(sa)
    r = c.get("/api/v1/admin/settings/mail")
    assert (
        r.status_code == 200 and r.json()["enabled"] is False and r.json()["has_password"] is False
    )
    body = {
        "enabled": True,
        "host": "smtp.example.com",
        "port": 587,
        "username": "u",
        "password": "sekret",
        "use_tls": True,
        "from_email": "Termolink <noreply@example.com>",
    }
    r = c.put("/api/v1/admin/settings/mail", body, content_type="application/json")
    assert r.status_code == 200, r.content
    assert r.json()["has_password"] is True and "password" not in r.json()
    row = MailSettings.load()
    assert row.password_enc is not None and b"sekret" not in bytes(row.password_enc)
    assert mail.get_password(row) == "sekret"
    # omitting password keeps it; empty string clears it
    c.put("/api/v1/admin/settings/mail", {"port": 2525}, content_type="application/json")
    assert mail.get_password(MailSettings.load()) == "sekret"
    c.put("/api/v1/admin/settings/mail", {"password": ""}, content_type="application/json")
    assert MailSettings.load().password_enc is None
    r = c.put(
        "/api/v1/admin/settings/mail",
        {"use_tls": True, "use_ssl": True},
        content_type="application/json",
    )
    assert r.status_code == 400
    r = c.put(
        "/api/v1/admin/settings/mail",
        {"enabled": True, "host": ""},
        content_type="application/json",
    )
    assert r.status_code == 400 and "host" in r.json()["error"]["fields"]


@pytest.mark.django_db
def test_backend_uses_db_settings_and_from_address(settings: Any, monkeypatch: Any) -> None:
    row = MailSettings.load()
    row.enabled, row.host, row.port, row.from_email = (
        True,
        "smtp.example.com",
        2525,
        "Ops <ops@example.com>",
    )
    mail.set_password(row, "pw")
    row.save()
    mail.invalidate()
    captured: dict[str, Any] = {}

    class FakeSmtp:
        def __init__(self, **kw: Any) -> None:
            captured.update(kw)

        def send_messages(self, messages: list[Any]) -> int:
            captured["from"] = messages[0].from_email
            return len(messages)

    monkeypatch.setattr(mail, "SmtpBackend", FakeSmtp)
    settings.EMAIL_BACKEND = "apps.core.mail.DatabaseEmailBackend"
    assert django_mail.send_mail("s", "b", None, ["x@example.com"]) == 1
    assert captured["host"] == "smtp.example.com" and captured["port"] == 2525
    assert (
        captured["password"] == "pw"
        and captured["use_tls"] is True
        and captured["use_ssl"] is False
    )
    assert captured["from"] == "Ops <ops@example.com>"


@pytest.mark.django_db
def test_mail_test_endpoint_records_outcome(monkeypatch: Any) -> None:
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    c = _login(sa)
    row = MailSettings.load()
    row.enabled, row.host = True, "smtp.invalid"
    row.save()

    class Boom:
        def __init__(self, **kw: Any) -> None:
            pass

        def send_messages(self, messages: list[Any]) -> int:
            raise OSError("connection refused")

    monkeypatch.setattr(mail, "SmtpBackend", Boom)
    r = c.post(
        "/api/v1/admin/settings/mail/test",
        {"to": "me@example.com"},
        content_type="application/json",
    )
    assert (
        r.status_code == 200
        and r.json()["ok"] is False
        and "connection refused" in r.json()["error"]
    )
    assert MailSettings.load().last_test_ok is False

    class Fine(Boom):
        def send_messages(self, messages: list[Any]) -> int:
            return 1

    monkeypatch.setattr(mail, "SmtpBackend", Fine)
    r = c.post(
        "/api/v1/admin/settings/mail/test",
        {"to": "me@example.com"},
        content_type="application/json",
    )
    assert r.json()["ok"] is True and MailSettings.load().last_test_ok is True
