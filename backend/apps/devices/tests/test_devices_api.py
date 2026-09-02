"""Devices API (docs/04 §Urządzenia) — create from discovered, details, patch (mode + reauth),
refresh from reserve, features, history (raw/1h/1d), status history, archive."""

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.adapters.base import Feature, PropertyDef
from apps.audit.models import AuditLog
from apps.devices.models import Device, DiscoveredDevice, FeatureValue
from apps.ingest import status as dstatus
from apps.ingest.models import Job
from apps.ingest.services import ingest
from apps.providers.models import ApiCall, ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)


@pytest.fixture
def world() -> dict[str, Any]:
    tenant = Tenant.objects.create(name="A")
    account = ProviderAccount.objects.create(
        tenant=tenant, provider="viessmann", refresh_token_enc=b"v1|x"
    )
    DiscoveredDevice.objects.create(
        tenant=tenant,
        provider_account=account,
        installation_id="1",
        gateway_serial="G",
        device_id="0",
        model="Vitocal250A",
        device_type="heating",
        online=True,
    )
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    admin = User.objects.create_user(
        "aa@example.com", PASSWORD, role=Role.TENANT_ADMIN, tenant=tenant
    )
    user = User.objects.create_user(
        "ua@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant
    )
    return {"tenant": tenant, "account": account, "sa": sa, "admin": admin, "user": user}


def login(user: User) -> Client:
    client = Client()
    r = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    if user.is_operator:
        user.totp_enabled = True
        user.save(update_fields=["totp_enabled"])
    return client


def post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, body, content_type="application/json")


def patch(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.patch(url, body, content_type="application/json")


@pytest.mark.django_db
def test_operator_creates_device_from_discovered_and_first_poll_is_queued(
    world: dict[str, Any],
) -> None:
    tid, acc = world["tenant"].id, world["account"]
    client = login(world["sa"])
    body = {
        "provider_account_id": str(acc.id),
        "external_ids": {"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        "display_name": "Pompa ciepła — dom",
        "location_text": "Olsztyn",
        "mode": "read",
    }
    r = post(client, f"/api/v1/tenants/{tid}/devices", body)
    assert r.status_code == 201, r.content
    d = r.json()
    assert d["model"] == "Vitocal250A" and d["status"] == "unknown" and d["mode"] == "read"
    assert (
        d["capabilities"]["can_control"] is False
        and "device_read_only" in d["capabilities"]["reasons"]
    )
    assert d["budget"]["limit"] == 1450 and d["effective_interval_s"] >= 60
    assert Job.objects.filter(kind="poll", payload__device_id=d["id"]).exists()
    assert post(client, f"/api/v1/tenants/{tid}/devices", body).status_code == 409
    assert AuditLog.objects.filter(action="device.created").exists()

    # tenant_admin cannot create, tenant_user cannot even list? (list is for everyone)
    assert post(login(world["admin"]), f"/api/v1/tenants/{tid}/devices", body).status_code == 403
    r = login(world["user"]).get(f"/api/v1/tenants/{tid}/devices")
    assert (
        r.status_code == 200
        and r.json()["count"] == 1
        and r.json()["results"][0]["highlights"] == []
    )


@pytest.mark.django_db
def test_patch_permissions_and_mode_requires_reauth(world: dict[str, Any]) -> None:
    tid = world["tenant"].id
    device = Device.objects.create(
        tenant=world["tenant"],
        provider_account=world["account"],
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        display_name="X",
    )
    url = f"/api/v1/tenants/{tid}/devices/{device.id}"
    admin = login(world["admin"])
    assert (
        patch(admin, url, {"display_name": "Nowa nazwa", "description": "opis"}).status_code == 200
    )
    r = patch(admin, url, {"mode": "control"})
    assert r.status_code == 403  # tenant_admin cannot change mode
    assert (
        login(world["user"])
        .patch(url, {"display_name": "x"}, content_type="application/json")
        .status_code
        == 403
    )

    sa = login(world["sa"])
    r = patch(sa, url, {"mode": "control"})
    assert r.status_code == 428 and r.json()["error"]["code"] == "reauth_required"
    from apps.accounts.totp import hash_backup_code

    world["sa"].backup_codes_hash = [hash_backup_code("abcdef0123")]
    world["sa"].save(update_fields=["backup_codes_hash"])
    r = post(sa, "/api/v1/auth/reauth", {"password": PASSWORD, "totp": "abcdef0123"})
    assert r.status_code == 204, r.content
    r = patch(sa, url, {"mode": "control", "poll_interval_s": 900})
    assert (
        r.status_code == 200
        and r.json()["mode"] == "control"
        and r.json()["poll_interval_s"] == 900
    )
    assert AuditLog.objects.filter(action="device.mode.changed").exists()
    device.refresh_from_db()
    assert device.display_name == "Nowa nazwa" and device.mode == "control"


@pytest.mark.django_db
def test_refresh_uses_reserve_and_429_when_exhausted(world: dict[str, Any]) -> None:
    tid, acc = world["tenant"].id, world["account"]
    device = Device.objects.create(
        tenant=world["tenant"],
        provider_account=acc,
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        display_name="X",
    )
    url = f"/api/v1/tenants/{tid}/devices/{device.id}/refresh"
    admin = login(world["admin"])
    r = admin.post(url)
    assert r.status_code == 202 and "job_id" in r.json()
    assert admin.post(url).json()["job_id"] == r.json()["job_id"]  # de-duplicated while pending
    job = Job.objects.get(public_id=r.json()["job_id"])
    assert job.payload["kind"] == "refresh" and job.priority == 10
    assert login(world["user"]).post(url).status_code == 403

    ApiCall.objects.bulk_create(
        [
            ApiCall(provider_account=acc, kind="command", ts=timezone.now(), http_status=200)
            for _ in range(acc.reserve)
        ]
    )
    Job.objects.filter(id=job.id).update(status="done")
    r = admin.post(url)
    assert r.status_code == 429 and r.json()["error"]["code"] == "budget_reserve_exhausted"


@pytest.mark.django_db
def test_features_history_and_status_history(world: dict[str, Any]) -> None:
    tid = world["tenant"].id
    device = Device.objects.create(
        tenant=world["tenant"],
        provider_account=world["account"],
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        display_name="X",
    )
    t0 = timezone.now() - timedelta(hours=30)
    for i in range(30):
        ingest(
            device,
            [
                Feature(
                    name="heating.sensors.temperature.outside",
                    enabled=True,
                    ready=True,
                    properties={
                        "value": PropertyDef("value", "number", "celsius", 10 + i % 5, None)
                    },
                    commands={},
                    raw={},
                )
            ],
            polled_at=t0 + timedelta(hours=i),
        )
    dstatus.mark_online(device)
    dstatus.mark_offline(device, "GATEWAY_OFFLINE")
    client = login(world["user"])

    r = client.get(f"/api/v1/tenants/{tid}/devices/{device.id}/features")
    assert r.status_code == 200 and r.json()["count"] == 1
    feat = r.json()["results"][0]
    assert feat["group_key"] == "sensors" and feat["properties"]["value"]["unit"] == "celsius"
    assert feat["properties"]["value"]["value"] == 10 + 29 % 5

    feature_name = "heating.sensors.temperature.outside"
    base = f"/api/v1/tenants/{tid}/devices/{device.id}/history?feature={feature_name}"
    r = client.get(
        f"{base}&from={(t0 - timedelta(hours=1)).isoformat()}&to={timezone.now().isoformat()}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolution"] == "raw" and len(body["points"]) == 30 and body["unit"] == "celsius"
    assert (
        body["stats"]["min"] == 10 and body["stats"]["max"] == 14 and body["stats"]["count"] == 30
    )
    r = client.get(
        f"{base}&from={(t0 - timedelta(days=10)).isoformat()}&to={timezone.now().isoformat()}"
    )
    assert r.json()["resolution"] == "1h" and len(r.json()["points"]) == 30
    r = client.get(
        f"{base}&from={(t0 - timedelta(days=10)).isoformat()}"
        f"&to={timezone.now().isoformat()}&resolution=1d"
    )
    assert r.json()["resolution"] == "1d" and 2 <= len(r.json()["points"]) <= 3
    assert r.json()["points"][0]["count"] >= 1 and "avg" in r.json()["points"][0]
    r = client.get(f"{base}&max_points=10&from={(t0 - timedelta(hours=1)).isoformat()}")
    assert len(r.json()["points"]) == 10
    assert client.get(f"/api/v1/tenants/{tid}/devices/{device.id}/history").status_code == 400
    assert client.get(f"{base}&resolution=5m").status_code == 400

    r = client.get(f"/api/v1/tenants/{tid}/devices/{device.id}/status-history")
    assert [row["status"] for row in r.json()["results"]] == ["offline", "online"]

    # the device card now shows the outside temperature as a highlight
    r = client.get(f"/api/v1/tenants/{tid}/devices")
    assert r.json()["results"][0]["highlights"][0]["label"] == "Temp. zewnętrzna"
    assert r.json()["results"][0]["status"] == "offline"


@pytest.mark.django_db
def test_archive_hides_device_and_cancels_polls(world: dict[str, Any]) -> None:
    tid = world["tenant"].id
    device = Device.objects.create(
        tenant=world["tenant"],
        provider_account=world["account"],
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        display_name="X",
    )
    from apps.ingest import queue

    job = queue.enqueue("poll", {"device_id": str(device.id)}, tenant=world["tenant"])
    sa = login(world["sa"])
    assert sa.delete(f"/api/v1/tenants/{tid}/devices/{device.id}").status_code == 204
    assert sa.get(f"/api/v1/tenants/{tid}/devices/{device.id}").status_code == 404
    assert sa.get(f"/api/v1/tenants/{tid}/devices").json()["count"] == 0
    job.refresh_from_db()
    assert job.status == "failed"
    assert (
        login(world["admin"]).delete(f"/api/v1/tenants/{tid}/devices/{device.id}").status_code
        == 403
    )
    assert FeatureValue.objects.count() == 0
