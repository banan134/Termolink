"""docs/10 §Alarmy: offline after N minutes, dedup, auto-close, out-of-range, messages, e-mail."""

from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.alerts import services
from apps.alerts.models import Alert, AlertRule, AlertType
from apps.devices.models import Device, FeatureLatest, FeatureValue
from apps.ingest import status as dstatus
from apps.ingest.models import WorkerHeartbeat
from apps.providers.models import AccountStatus, ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


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
    )
    admin = User.objects.create_user(
        "aa@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )
    user = User.objects.create_user(
        "ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant
    )
    return {"tenant": tenant, "account": account, "device": device, "admin": admin, "user": user}


def login(user: User) -> Client:
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return c


@pytest.mark.django_db
def test_offline_alert_after_30_minutes_dedup_and_autoclose(world: dict[str, Any]) -> None:
    device = world["device"]
    now = timezone.now()
    dstatus.mark_offline(device, "gateway offline", at=now - timedelta(minutes=10))
    assert services.evaluate_offline(now) == 0  # too early
    Device.objects.filter(id=device.id).update(status_since=now - timedelta(minutes=31))
    device.refresh_from_db()
    assert services.evaluate_offline(now) == 1
    assert services.evaluate_offline(now) == 0  # dedup: still one open alert
    alert = Alert.objects.get(type=AlertType.DEVICE_OFFLINE)
    assert alert.severity == "critical" and alert.device == device and alert.closed_at is None
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["aa@example.com"]
    assert "alarm" in mail.outbox[0].subject
    dstatus.mark_online(device)
    services.evaluate_offline(timezone.now())
    alert.refresh_from_db()
    assert alert.closed_at is not None


@pytest.mark.django_db
def test_offline_rule_minutes_and_disabled(world: dict[str, Any]) -> None:
    device = world["device"]
    now = timezone.now()
    rule = AlertRule.objects.create(
        tenant=world["tenant"], type=AlertType.DEVICE_OFFLINE, config={"minutes": 5, "email": False}
    )
    dstatus.mark_offline(device, "x", at=now - timedelta(minutes=6))
    device.refresh_from_db()
    assert services.evaluate_offline(now) == 1
    assert mail.outbox == []  # email disabled in the rule
    rule.enabled = False
    rule.save()
    services.evaluate_offline(now)
    assert Alert.objects.filter(closed_at__isnull=True).count() == 0


def _history(device: Device, feature: str, values: list[float]) -> None:
    base = timezone.now()  # strictly increasing timestamps across calls
    FeatureValue.objects.bulk_create(
        [
            FeatureValue(
                tenant=device.tenant,
                device=device,
                feature_name=feature,
                property_name="value",
                ts_polled=base + timedelta(milliseconds=i),
                value_num=v,
            )
            for i, v in enumerate(values)
        ]
    )
    FeatureLatest.objects.update_or_create(
        device=device,
        feature_name=feature,
        property_name="value",
        defaults={
            "tenant": device.tenant,
            "value_num": values[-1],
            "unit": "celsius",
            "ts_polled": timezone.now(),
        },
    )


@pytest.mark.django_db
def test_out_of_range_needs_two_consecutive_readings(world: dict[str, Any]) -> None:
    device = world["device"]
    feature = "heating.sensors.temperature.outside"
    AlertRule.objects.create(
        tenant=world["tenant"],
        type=AlertType.VALUE_OUT_OF_RANGE,
        config={"feature": feature, "property": "value", "min": -20, "max": 40},
    )
    _history(device, feature, [10, 45])  # only one outside
    assert services.evaluate_out_of_range(timezone.now()) == 0
    _history(device, feature, [46])
    assert services.evaluate_out_of_range(timezone.now()) == 1
    alert = Alert.objects.get(type=AlertType.VALUE_OUT_OF_RANGE)
    assert "poza zakresem" in alert.message and "celsius" in alert.message
    _history(device, feature, [20, 21])
    services.evaluate_out_of_range(timezone.now())
    alert.refresh_from_db()
    assert alert.closed_at is not None


@pytest.mark.django_db
def test_device_message_alert_opens_per_message_and_closes(world: dict[str, Any]) -> None:
    device = world["device"]
    FeatureLatest.objects.create(
        tenant=device.tenant,
        device=device,
        feature_name="device.messages.errors.raw",
        property_name="entries",
        value_json=[{"errorCode": "F.123", "priority": "error"}],
        ts_polled=timezone.now(),
    )
    assert services.evaluate_messages() == 1
    assert services.evaluate_messages() == 0
    FeatureLatest.objects.filter(device=device).update(value_json=[])
    services.evaluate_messages()
    assert Alert.objects.filter(type=AlertType.DEVICE_MESSAGE, closed_at__isnull=True).count() == 0


@pytest.mark.django_db
@override_settings(ALERT_EMAIL_OPERATOR="ops@wodmiar.example")
def test_provider_account_and_worker_alerts_go_to_operator(world: dict[str, Any]) -> None:
    account = world["account"]
    account.set_status(AccountStatus.REAUTH_REQUIRED, "invalid_grant")
    account.save()
    assert services.evaluate_provider_accounts() == 1
    assert mail.outbox[-1].to == ["ops@wodmiar.example"]
    WorkerHeartbeat.objects.create(
        worker_id="w1", last_beat_at=timezone.now() - timedelta(minutes=3)
    )
    assert services.evaluate_workers(timezone.now()) == 1
    assert Alert.objects.get(type=AlertType.WORKER_DOWN).tenant_id is None
    account.set_status(AccountStatus.ACTIVE)
    account.save()
    services.evaluate_provider_accounts()
    assert (
        Alert.objects.filter(type=AlertType.PROVIDER_ACCOUNT, closed_at__isnull=True).count() == 0
    )


@pytest.mark.django_db
def test_alerts_api_ack_and_rules_crud(world: dict[str, Any]) -> None:
    tid = world["tenant"].id
    services.open_alert(
        type=AlertType.DEVICE_OFFLINE, tenant=world["tenant"], device=world["device"], message="m"
    )
    c = login(world["admin"])
    r = c.get(f"/api/v1/tenants/{tid}/alerts?open=1")
    assert r.status_code == 200 and r.json()["count"] == 1 and r.json()["open_count"] == 1
    aid = r.json()["results"][0]["id"]
    r = c.patch(
        f"/api/v1/tenants/{tid}/alerts/{aid}",
        {"acknowledged": True},
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["acknowledged_by"] == "aa@example.com"

    r = c.post(
        f"/api/v1/tenants/{tid}/alert-rules",
        {"type": "device_offline", "config": {"minutes": 0}},
        content_type="application/json",
    )
    assert r.status_code == 400 and "minutes" in r.json()["error"]["fields"]
    r = c.post(
        f"/api/v1/tenants/{tid}/alert-rules",
        {
            "type": "value_out_of_range",
            "device_id": str(world["device"].id),
            "config": {"feature": "f", "min": 1, "max": 5},
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    rid = r.json()["id"]
    r = c.patch(
        f"/api/v1/tenants/{tid}/alert-rules/{rid}",
        {"enabled": False},
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert (
        c.get(f"/api/v1/tenants/{tid}/alert-rules").json()["results"][0]["device_name"] == "Kociol"
    )
    assert c.delete(f"/api/v1/tenants/{tid}/alert-rules/{rid}").status_code == 204

    u = login(world["user"])
    assert u.get(f"/api/v1/tenants/{tid}/alerts").status_code == 200
    r = u.post(
        f"/api/v1/tenants/{tid}/alert-rules",
        {"type": "device_message"},
        content_type="application/json",
    )
    assert r.status_code == 403
