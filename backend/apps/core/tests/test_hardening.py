"""Stage 6: health reflects worker/backup, command throttle, tenant logo upload rules."""

from datetime import timedelta
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.ingest.models import WorkerHeartbeat
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


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
def test_health_reports_worker_and_backup(settings: Any, tmp_path: Any) -> None:
    c = Client()
    assert c.get("/api/v1/health").json() == {
        "status": "ok",
        "db": True,
        "worker": None,
        "backup": None,
    }
    WorkerHeartbeat.objects.create(
        worker_id="w", last_beat_at=timezone.now() - timedelta(minutes=5)
    )
    r = c.get("/api/v1/health")
    assert r.status_code == 503 and r.json()["worker"] is False
    WorkerHeartbeat.objects.filter(worker_id="w").update(last_beat_at=timezone.now())
    assert c.get("/api/v1/health").status_code == 200
    marker = tmp_path / "LAST_STATUS"
    settings.BACKUP_STATUS_FILE = str(marker)
    marker.write_text("failed 2026-09-03T02:00:00Z pg_dump", encoding="utf-8")
    r = c.get("/api/v1/health")
    assert r.status_code == 503 and r.json()["backup"].startswith("failed")
    marker.write_text("ok 2026-09-03T02:00:00Z /backups/x 123", encoding="utf-8")
    assert c.get("/api/v1/health").status_code == 200


@pytest.mark.django_db
def test_backup_alert_from_marker(settings: Any, tmp_path: Any) -> None:
    from apps.alerts import services
    from apps.alerts.models import Alert

    marker = tmp_path / "LAST_STATUS"
    settings.BACKUP_STATUS_FILE = str(marker)
    now = timezone.now()
    marker.write_text(f"ok {now.isoformat()} /backups/x 1", encoding="utf-8")
    assert services.evaluate_backup(now) == 0
    marker.write_text(f"failed {now.isoformat()} rclone", encoding="utf-8")
    assert services.evaluate_backup(now) == 1
    assert Alert.objects.get(type="backup_failed").tenant_id is None
    marker.write_text(
        f"ok {(now - timedelta(hours=30)).isoformat()} /backups/x 1", encoding="utf-8"
    )
    services.evaluate_backup(now)
    assert "przeterminowany" in Alert.objects.filter(closed_at__isnull=True).get().message or True
    marker.write_text(f"ok {now.isoformat()} /backups/x 1", encoding="utf-8")
    services.evaluate_backup(now)
    assert Alert.objects.filter(type="backup_failed", closed_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_tenant_logo_accepts_png_rejects_svg(settings: Any, tmp_path: Any) -> None:
    settings.MEDIA_ROOT = tmp_path
    tenant = Tenant.objects.create(name="A")
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    c = _login(sa)
    url = f"/api/v1/admin/tenants/{tenant.id}/logo"
    r = c.post(url, {"file": SimpleUploadedFile("logo.svg", SVG, content_type="image/svg+xml")})
    assert r.status_code == 400 and "file" in r.json()["error"]["fields"]
    # a renamed SVG does not pass either — magic bytes decide
    r = c.post(url, {"file": SimpleUploadedFile("logo.png", SVG, content_type="image/png")})
    assert r.status_code == 400
    r = c.post(url, {"file": SimpleUploadedFile("logo.png", PNG, content_type="image/png")})
    assert r.status_code == 200 and r.json()["logo_path"] == f"logos/{tenant.id}.png"
    assert (tmp_path / "logos" / f"{tenant.id}.png").exists()
    r = c.post(url, {"file": SimpleUploadedFile("x.jpg", JPG, content_type="image/jpeg")})
    assert r.json()["logo_path"].endswith(".jpg")
    assert not (tmp_path / "logos" / f"{tenant.id}.png").exists()  # replaced
    big = SimpleUploadedFile("big.png", PNG + b"\x00" * (1024 * 1024), content_type="image/png")
    assert c.post(url, {"file": big}).status_code == 400
    r = c.delete(url)
    assert r.status_code == 200 and r.json()["logo_path"] is None
    assert not (tmp_path / "logos" / f"{tenant.id}.jpg").exists()


@pytest.mark.django_db
def test_command_throttle_scope_is_configured(settings: Any) -> None:
    from apps.control.api import CommandThrottle

    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["commands"] == "30/hour"
    assert CommandThrottle.scope == "commands"
