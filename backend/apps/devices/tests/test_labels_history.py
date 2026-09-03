"""feature_labels dictionary, history extensions (gaps, stats, LTTB, multi, CSV), messages."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.adapters.base import Feature, PropertyDef
from apps.devices import labels
from apps.devices.history import lttb
from apps.devices.models import Device, FeatureLabel
from apps.ingest import status as dstatus
from apps.ingest.services import ingest
from apps.providers.models import ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _ctx(db: None) -> None:
    set_context(SYSTEM)
    labels.invalidate()


def login(user: User) -> Client:
    c = Client()
    r = c.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    if user.is_operator:
        user.totp_enabled = True
        user.save(update_fields=["totp_enabled"])
    return c


def label_of(name: str) -> labels.Label:
    label = labels.resolve(name)
    assert label is not None, name
    return label


def numeric(name: str, value: float, unit: str | None = "celsius") -> Feature:
    return Feature(
        name=name,
        enabled=True,
        ready=True,
        properties={"value": PropertyDef("value", "number", unit, value, None)},
        commands={},
        raw={},
    )


@pytest.mark.django_db
def test_seed_dictionary_loaded_and_resolution_rules() -> None:
    assert FeatureLabel.objects.count() > 100
    assert label_of("heating.sensors.temperature.outside").label_pl == "Temperatura zewnętrzna"
    circuit = labels.resolve("heating.circuits.2.sensors.temperature.supply")
    assert (
        circuit is not None
        and circuit.label_pl == "Temperatura zasilania obiegu"
        and circuit.highlight
    )
    assert label_of("heating.circuits.0.heating.curve").command_property_map == {
        "setCurve": {"slope": "slope", "shift": "shift"}
    }
    assert labels.resolve("totally.unknown.feature") is None
    # exact beats wildcard, fewer wildcards beat more
    FeatureLabel.objects.create(feature_name_pattern="a.*.c", label_pl="wild")
    FeatureLabel.objects.create(feature_name_pattern="a.b.c", label_pl="exact")
    FeatureLabel.objects.create(feature_name_pattern="a.*.*", label_pl="wilder")
    labels.invalidate()
    assert label_of("a.b.c").label_pl == "exact"
    assert label_of("a.x.c").label_pl == "wild"
    assert label_of("a.x.y").label_pl == "wilder"


@pytest.mark.django_db
def test_import_is_idempotent_and_admin_api_replaces() -> None:
    before = FeatureLabel.objects.count()
    labels.import_csv()
    assert FeatureLabel.objects.count() == before
    sa = User.objects.create_superuser("sa@example.com", PASSWORD)
    c = login(sa)
    r = c.get("/api/v1/admin/feature-labels")
    assert r.status_code == 200 and r.json()["count"] == before
    rows = r.json()["results"]
    rows.append({"pattern": "x.y", "label_pl": "Nowa", "highlight": True, "sort": 1})
    r = c.put("/api/v1/admin/feature-labels", rows, content_type="application/json")
    assert r.status_code == 200 and r.json()["count"] == before + 1
    assert label_of("x.y").highlight
    dup = rows + [{"pattern": "x.y", "label_pl": "dup"}]
    assert (
        c.put("/api/v1/admin/feature-labels", dup, content_type="application/json").status_code
        == 400
    )
    tech = User.objects.create_user("t@example.com", PASSWORD, role=Role.TECHNICIAN)
    assert login(tech).get("/api/v1/admin/feature-labels").status_code == 403


def test_lttb_keeps_endpoints_and_peaks() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [(base + timedelta(minutes=i), 10.0) for i in range(200)]
    pts[100] = (pts[100][0], 99.0)  # a spike must survive
    out = lttb(pts, 20)
    assert len(out) == 20 and out[0] == pts[0] and out[-1] == pts[-1]
    assert any(v == 99.0 for _, v in out)
    assert lttb(pts[:5], 20) == pts[:5]


@pytest.fixture
def world() -> dict[str, Any]:
    tenant = Tenant.objects.create(name="A")
    account = ProviderAccount.objects.create(
        tenant=tenant, provider="viessmann", refresh_token_enc=b"v1|x"
    )
    device = Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "G", "deviceId": "0"},
        display_name="Kociol",
    )
    user = User.objects.create_user("u@example.com", PASSWORD, role=Role.TENANT_USER, tenant=tenant)
    t0 = timezone.now() - timedelta(hours=10)
    for i in range(60):
        ingest(
            device,
            [
                numeric("heating.sensors.temperature.outside", 10 + (i % 6)),
                numeric("heating.burners.0.statistics", 1000 + i, "hour"),
                Feature(
                    name="device.messages.status.raw",
                    enabled=True,
                    ready=True,
                    properties={
                        "entries": PropertyDef(
                            "entries", "array", None, [{"code": "F.1"}] if i % 30 == 5 else [], None
                        )
                    },
                    commands={},
                    raw={},
                ),
            ],
            polled_at=t0 + timedelta(minutes=10 * i),
        )
    dstatus.mark_online(device, at=t0)
    dstatus.mark_offline(device, "GATEWAY_OFFLINE", at=t0 + timedelta(hours=2))
    dstatus.mark_online(device, at=t0 + timedelta(hours=3))
    return {"tenant": tenant, "device": device, "user": user, "t0": t0}


@pytest.mark.django_db
def test_features_carry_labels_and_highlights_from_dictionary(world: dict[str, Any]) -> None:
    c = login(world["user"])
    tid, did = world["tenant"].id, world["device"].id
    rows = c.get(f"/api/v1/tenants/{tid}/devices/{did}/features").json()["results"]
    by = {r["feature_name"]: r for r in rows}
    assert by["heating.sensors.temperature.outside"]["label_pl"] == "Temperatura zewnętrzna"
    assert (
        by["heating.burners.0.statistics"]["group_key"] == "statistics"
    )  # dictionary override of heat_source
    assert by["device.messages.status.raw"]["group_key"] == "messages"
    assert [r["feature_name"] for r in rows][
        0
    ] == "heating.sensors.temperature.outside"  # sensors first
    cards = c.get(f"/api/v1/tenants/{tid}/devices").json()["results"]
    assert cards[0]["highlights"][0]["label"] == "Temperatura zewnętrzna"


@pytest.mark.django_db
def test_history_gaps_stats_delta_and_downsampling(world: dict[str, Any]) -> None:
    c = login(world["user"])
    tid, did, t0 = world["tenant"].id, world["device"].id, world["t0"]
    since = (t0 - timedelta(minutes=1)).isoformat()
    base = (
        f"/api/v1/tenants/{tid}/devices/{did}/history?from={since}&to={timezone.now().isoformat()}"
    )
    r = c.get(f"{base}&feature=heating.sensors.temperature.outside").json()
    assert r["resolution"] == "raw" and len(r["points"]) == 60 and r["downsampled"] is False
    assert (
        r["stats"]["min"]["value"] == 10
        and r["stats"]["max"]["value"] == 15
        and "ts" in r["stats"]["max"]
    )
    assert 0 < r["stats"]["availability_pct"] < 100 and len(r["gaps"]) == 1
    gap = r["gaps"][0]
    assert gap["from"] and gap["to"]
    assert r["markers"] == [] and "delta" not in r["stats"]
    r = c.get(f"{base}&feature=heating.burners.0.statistics&max_points=12").json()
    assert r["downsampled"] is True and len(r["points"]) == 12
    assert r["stats"]["delta"] == 59.0  # counter: last - first


@pytest.mark.django_db
def test_history_multi_and_csv(world: dict[str, Any]) -> None:
    c = login(world["user"])
    tid, did, t0 = world["tenant"].id, world["device"].id, world["t0"]
    body = {
        "series": [
            {"device_id": str(did), "feature": "heating.sensors.temperature.outside"},
            {"device_id": str(did), "feature": "heating.burners.0.statistics", "property": "value"},
        ],
        "from": (t0 - timedelta(minutes=1)).isoformat(),
        "resolution": "1h",
    }
    r = c.post(f"/api/v1/tenants/{tid}/history/multi", body, content_type="application/json")
    assert r.status_code == 200, r.content
    assert r.json()["count"] == 2 and all(s["resolution"] == "1h" for s in r.json()["results"])
    too_many = {**body, "series": body["series"] * 4}
    assert (
        c.post(
            f"/api/v1/tenants/{tid}/history/multi", too_many, content_type="application/json"
        ).status_code
        == 400
    )

    since = (t0 - timedelta(minutes=1)).isoformat()

    r = c.get(
        f"/api/v1/tenants/{tid}/devices/{did}/history.csv"
        f"?feature=heating.sensors.temperature.outside&from={since}"
    )
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿czas;urządzenie;cecha;właściwość;wartość;jednostka")
    assert text.count("\n") == 61 and ";Kociol;heating.sensors.temperature.outside;value;" in text
    assert r["Content-Disposition"].startswith('attachment; filename="termolink_Kociol_')


@pytest.mark.django_db
def test_messages_endpoint(world: dict[str, Any]) -> None:
    c = login(world["user"])
    tid, did = world["tenant"].id, world["device"].id
    r = c.get(f"/api/v1/tenants/{tid}/devices/{did}/messages")
    assert r.status_code == 200
    body = r.json()
    assert [f["feature_name"] for f in body["features"]] == ["device.messages.status.raw"]
    assert len(body["history"]) >= 3  # [] → F.1 → [] → F.1 …
    assert any(h["value"] == [{"code": "F.1"}] for h in body["history"])
