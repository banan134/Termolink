"""Insights (period vs previous period) and the operator overview."""

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.alerts.models import Alert
from apps.devices import insights
from apps.devices.models import Device, FeatureLatest, FeatureValue
from apps.providers.models import ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"
HOURS = "heating.burners.0.statistics"
TEMP = "heating.sensors.temperature.outside"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


def _write(device: Device, feature: str, prop: str, unit: str, fn: Any, days: int = 14) -> None:
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    rows = []
    for h in range(days * 24):
        ts = start + timedelta(hours=h)
        rows.append(
            FeatureValue(
                tenant=device.tenant,
                device=device,
                feature_name=feature,
                property_name=prop,
                ts_polled=ts,
                value_num=fn(h),
            )
        )
    FeatureValue.objects.bulk_create(rows)
    FeatureLatest.objects.create(
        tenant=device.tenant,
        device=device,
        feature_name=feature,
        property_name=prop,
        value_num=fn(days * 24 - 1),
        unit=unit,
        ts_polled=now,
    )


@pytest.fixture
def world() -> dict[str, Any]:
    tenant = Tenant.objects.create(name="A")
    account = ProviderAccount.objects.create(tenant=tenant, provider="viessmann")
    device = Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"deviceId": "0"},
        display_name="Kociol",
        lat=53.77,
        lon=20.49,
        status="online",
    )
    # burner hours: 1 h/h in the previous week, 2 h/h in the current week (168 h boundary)
    _write(device, HOURS, "hours", "hour", lambda h: float(h if h < 168 else 168 + 2 * (h - 168)))
    # outside temperature: 10 °C previous week, 15 °C current week
    _write(device, TEMP, "value", "celsius", lambda h: 10.0 if h < 168 else 15.0)
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    user = User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    return {"tenant": tenant, "device": device, "sa": sa, "user": user}


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
def test_insights_week_over_week(world: dict[str, Any]) -> None:
    data = insights.compute(world["device"], period="week")
    by = {i["feature"]: i for i in data["items"] if i["feature"]}
    hours = by[HOURS]
    assert hours["kind"] == "counter"
    assert hours["previous"] == pytest.approx(167, abs=2) and hours["current"] == pytest.approx(
        334, abs=4
    )
    assert hours["delta_pct"] == pytest.approx(100, abs=5)
    temp = by[TEMP]
    assert (
        temp["kind"] == "average"
        and temp["previous"] == pytest.approx(10, abs=0.5)
        and temp["current"] == pytest.approx(15, abs=0.5)
        and temp["delta"] == pytest.approx(5, abs=1)
    )
    avail = next(i for i in data["items"] if i["kind"] == "availability")
    assert avail["current"] == 100.0


@pytest.mark.django_db
def test_insights_endpoint_and_isolation(world: dict[str, Any]) -> None:
    tid, did = world["tenant"].id, world["device"].id
    c = _login(world["user"])
    r = c.get(f"/api/v1/tenants/{tid}/devices/{did}/insights?period=month")
    assert r.status_code == 200 and r.json()["days"] == 30 and len(r.json()["items"]) >= 3
    other = Tenant.objects.create(name="B")
    assert c.get(f"/api/v1/tenants/{other.id}/devices/{did}/insights").status_code == 404


@pytest.mark.django_db
def test_operator_overview(world: dict[str, Any]) -> None:
    Alert.objects.create(
        tenant=world["tenant"], device=world["device"], type="device_offline", message="m"
    )
    Alert.objects.create(tenant=None, type="worker_down", message="w")
    c = _login(world["sa"])
    r = c.get("/api/v1/admin/overview")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["totals"]["devices"] == 1 and body["totals"]["open_alerts"] == 2
    dev = body["tenants"][0]["devices"][0]
    assert dev["lat"] == 53.77 and dev["open_alerts"] == 1 and dev["tenant_name"] == "A"
    assert body["accounts"][0]["budget"]["limit"] > 0
    assert _login(world["user"]).get("/api/v1/admin/overview").status_code == 403
