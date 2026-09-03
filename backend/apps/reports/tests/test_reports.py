"""docs/13 stage 5: monthly report equals the database (comparison test), CSV, PDF, schedules."""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.devices.models import Device, FeatureLatest, FeatureValue
from apps.ingest import status as dstatus
from apps.ingest.worker import Worker
from apps.providers.models import ProviderAccount
from apps.reports import jobs, render, services
from apps.reports.models import FileStatus, ReportFile, ReportSchedule
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"
TEMP = "heating.sensors.temperature.outside"
HOURS = "heating.burners.0.statistics"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


def _write(
    device: Device, feature: str, prop: str, unit: str, values: list[tuple[datetime, float]]
) -> None:
    FeatureValue.objects.bulk_create(
        [
            FeatureValue(
                tenant=device.tenant,
                device=device,
                feature_name=feature,
                property_name=prop,
                ts_polled=ts,
                value_num=v,
            )
            for ts, v in values
        ]
    )
    FeatureLatest.objects.create(
        tenant=device.tenant,
        device=device,
        feature_name=feature,
        property_name=prop,
        value_num=values[-1][1],
        unit=unit,
        ts_polled=values[-1][0],
    )


@pytest.fixture
def world(tmp_path: Any, settings: Any) -> dict[str, Any]:
    settings.MEDIA_ROOT = tmp_path
    tenant = Tenant.objects.create(name="Jeziorna", report_header_text="Wspólnota Jeziorna 5")
    account = ProviderAccount.objects.create(tenant=tenant, provider="viessmann")
    device = Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"deviceId": "0"},
        display_name="Kociol",
        model="E3_Vitodens_200",
    )
    start = datetime(2026, 8, 1, tzinfo=UTC)
    # hourly temperature 1..24 repeating for 31 days; burner hours counter with a reset on day 10
    temps = [(start + timedelta(hours=h), float(h % 24 + 1)) for h in range(31 * 24)]
    _write(device, TEMP, "value", "celsius", temps)
    hours = []
    for h in range(31 * 24):
        ts = start + timedelta(hours=h)
        hours.append((ts, float(h if h < 240 else h - 240)))  # reset at h=240
    _write(device, HOURS, "hours", "hour", hours)
    # 3 h offline gap inside the month
    dstatus.set_status(device, "online", at=start)
    dstatus.set_status(device, "offline", "gw", at=start + timedelta(days=5))
    dstatus.set_status(device, "online", at=start + timedelta(days=5, hours=3))
    admin = User.objects.create_user(
        "aa@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )
    user = User.objects.create_user(
        "ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant
    )
    return {"tenant": tenant, "device": device, "admin": admin, "user": user, "start": start}


def login(user: User) -> Client:
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return c


def body(world: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "report_type": "operation",
        "device_ids": [str(world["device"].id)],
        "from": "2026-08-01T00:00:00Z",
        "to": "2026-09-01T00:00:00Z",
        **extra,
    }


@pytest.mark.django_db
def test_monthly_operation_report_matches_database(world: dict[str, Any]) -> None:
    """Comparison test: min/max/avg/availability/delta recomputed independently from the rows."""
    params = services.parse_params(world["tenant"], body(world, resolution="1d"))
    data = services.build(world["tenant"], params)
    dev = data["devices"][0]
    temp = next(s for s in dev["series"] if s["feature"] == TEMP)
    assert temp["stats"]["min"]["value"] == pytest.approx(12.5)  # daily avg of 1..24
    assert temp["stats"]["max"]["value"] == pytest.approx(12.5)
    assert temp["stats"]["count"] == 31 * 24 and len(temp["points"]) == 31
    hours = next(s for s in dev["series"] if s["feature"] == HOURS)
    assert hours["counter"] is True
    # daily "last" values: 23, 47, ..., 239, then reset → 23, 47 ...; sum of rising segments
    lasts = [float(p["last"]) for p in hours["points"]]
    assert hours["stats"]["delta"] == pytest.approx(services.counter_delta(lasts))
    # day0..day9: 239-23, reset → +23 (day10 last), day10..day30: 503-23; the increase inside
    # the very first bucket is not visible from bucket `last` values (documented in docs/10)
    assert hours["stats"]["delta"] == pytest.approx(216 + 23 + 480)
    # availability: 3 h offline out of 31 d
    assert dev["availability_pct"] == pytest.approx(round(100 * (1 - 3 / (31 * 24)), 1))
    assert len(dev["offline"]) == 1 and dev["offline"][0]["seconds"] == 3 * 3600


def test_counter_delta_handles_reset() -> None:
    assert services.counter_delta([10, 12, 15]) == 5
    assert services.counter_delta([10, 12, 2, 5]) == 2 + 2 + 3  # reset at 2 → count from 0
    assert services.counter_delta([100, 101, 99.5, 102]) == 1 + 2.5  # noise drop ignored
    assert services.counter_delta([5]) is None


@pytest.mark.django_db
def test_preview_api_and_limits(world: dict[str, Any]) -> None:
    c = login(world["user"])
    tid = world["tenant"].id
    r = c.post(
        f"/api/v1/tenants/{tid}/reports/preview", body(world), content_type="application/json"
    )
    assert r.status_code == 200 and r.json()["devices"][0]["name"] == "Kociol"
    assert r.json()["resolution"] in ("1h", "1d")
    r = c.post(
        f"/api/v1/tenants/{tid}/reports/preview",
        body(world, device_ids=[]),
        content_type="application/json",
    )
    assert r.status_code == 400
    r = c.post(
        f"/api/v1/tenants/{tid}/reports/preview",
        body(world, report_type="energy"),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["devices"][0]["energy_available"] is True
    r = c.post(
        f"/api/v1/tenants/{tid}/reports/preview",
        body(world, report_type="availability"),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["devices"][0]["alerts"] == []
    r = c.post(
        f"/api/v1/tenants/{tid}/reports/preview",
        body(world, report_type="changes"),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["devices"][0]["commands"] == []


@pytest.mark.django_db
def test_csv_job_and_download(world: dict[str, Any]) -> None:
    c = login(world["admin"])
    tid = world["tenant"].id
    r = c.post(
        f"/api/v1/tenants/{tid}/reports/jobs",
        body(world, format="csv", resolution="1d"),
        content_type="application/json",
    )
    assert r.status_code == 202, r.content
    fid = r.json()["file_id"]
    assert (
        c.get(f"/api/v1/tenants/{tid}/reports/files/{fid}/download").status_code == 404
    )  # not ready
    Worker(concurrency=2).run_once()
    f = ReportFile.objects.get(id=fid)
    assert f.status == FileStatus.DONE, f.error
    r = c.get(f"/api/v1/tenants/{tid}/reports/files/{fid}/download")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    content = b"".join(r.streaming_content).decode("utf-8")  # type: ignore[attr-defined]
    assert content.startswith("﻿czas;urządzenie;cecha;właściwość;wartość;jednostka")
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿")), delimiter=";"))
    assert len(rows) == 1 + 31 * 2  # header + 31 days × 2 features
    r = c.get(f"/api/v1/tenants/{tid}/reports/files")
    assert r.json()["results"][0]["filename"].endswith(".csv")
    assert (
        login(world["user"]).delete(f"/api/v1/tenants/{tid}/reports/files/{fid}").status_code == 403
    )
    assert c.delete(f"/api/v1/tenants/{tid}/reports/files/{fid}").status_code == 204


@pytest.mark.django_db
def test_pdf_render_has_header_and_pages(world: dict[str, Any]) -> None:
    pytest.importorskip("weasyprint")
    params = services.parse_params(world["tenant"], body(world, resolution="1d"))
    html = render.render_html(services.build(world["tenant"], params), world["tenant"])
    assert "Wspólnota Jeziorna 5" in html and "<svg" in html and "Przerwy w łączności" in html
    pdf = render.render_pdf(html)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000


@pytest.mark.django_db
def test_schedule_runs_on_cron_and_mails_link(world: dict[str, Any]) -> None:
    c = login(world["admin"])
    tid = world["tenant"].id
    r = c.post(
        f"/api/v1/tenants/{tid}/report-schedules",
        {
            "name": "Miesięczny",
            "report_type": "operation",
            "device_ids": [str(world["device"].id)],
            "period": "last_month",
            "format": "csv",
            "recipients": ["zarzad@example.com"],
            "cron": "0 6 1 * *",
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    sid = r.json()["id"]
    r = c.post(
        f"/api/v1/tenants/{tid}/report-schedules",
        {
            "name": "x",
            "report_type": "operation",
            "device_ids": [str(world["device"].id)],
            "cron": "bad",
        },
        content_type="application/json",
    )
    assert r.status_code == 400
    ReportSchedule.objects.filter(id=sid).update(created_at=datetime(2026, 8, 20, tzinfo=UTC))
    assert jobs.schedule_reports(datetime(2026, 8, 31, 12, tzinfo=UTC)) == 0  # cron not yet due
    assert jobs.schedule_reports(datetime(2026, 9, 1, 8, tzinfo=UTC)) == 1  # 06:00 Warsaw passed
    assert jobs.schedule_reports(datetime(2026, 9, 1, 9, tzinfo=UTC)) == 0  # not twice
    file = ReportFile.objects.get(schedule_id=sid)
    assert file.params["from"].startswith("2026-08-01") and file.params["to"].startswith(
        "2026-09-01"
    )
    Worker(concurrency=2).run_once()
    file.refresh_from_db()
    assert file.status == FileStatus.DONE, file.error
    assert mail.outbox[-1].to == ["zarzad@example.com"] and "Miesięczny" in mail.outbox[-1].subject
    # run now + retention
    assert c.post(f"/api/v1/tenants/{tid}/report-schedules/{sid}").status_code == 202
    ReportFile.objects.update(expires_at=timezone.now() - timedelta(days=1))
    assert jobs.purge_expired() == 2


def test_period_range_warsaw() -> None:
    start, end = services.period_range(
        "last_month", "Europe/Warsaw", datetime(2026, 9, 3, 12, tzinfo=UTC)
    )
    assert (start.month, start.day, end.month, end.day) == (8, 1, 9, 1)
    start, end = services.period_range(
        "last_week", "Europe/Warsaw", datetime(2026, 9, 3, 12, tzinfo=UTC)
    )
    assert start.weekday() == 0 and (end - start).days == 7 and end.day == 31
    start, end = services.period_range(
        "last_day", "Europe/Warsaw", datetime(2026, 9, 3, 12, tzinfo=UTC)
    )
    assert (start.day, end.day) == (2, 3)


@pytest.mark.django_db
def test_html_preview_operator_only(world: dict[str, Any]) -> None:
    c = login(world["admin"])
    r = c.post(
        f"/api/v1/tenants/{world['tenant'].id}/reports/preview.html",
        body(world),
        content_type="application/json",
    )
    assert r.status_code == 403


@pytest.mark.django_db
@override_settings(ALERT_EMAIL_OPERATOR="")
def test_worker_tick_schedules_reports(world: dict[str, Any]) -> None:
    ReportSchedule.objects.create(
        tenant=world["tenant"],
        name="s",
        report_type="availability",
        device_ids=[world["device"].id],
        cron="* * * * *",
        format="csv",
        created_at=timezone.now() - timedelta(minutes=5),
    )
    Worker(concurrency=2).run_once()
    assert ReportFile.objects.count() == 1
