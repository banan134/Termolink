"""Ingest + status tests (docs/12 §Ingest) on constructed Feature objects."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.adapters.base import CommandDef, Feature, ParamDef, PropertyDef
from apps.devices.models import (
    Device,
    DeviceStatus,
    DeviceStatusHistory,
    FeatureDefinition,
    FeatureJsonHistory,
    FeatureLatest,
    FeatureValue,
)
from apps.ingest import status
from apps.ingest.services import ingest
from apps.providers.models import ProviderAccount
from apps.tenants.context import SYSTEM, set_context
from apps.tenants.models import Tenant


@pytest.fixture(autouse=True)
def _system_context(db: None) -> None:
    """Ingest writes through the feature_values_rls view, which needs an RLS context."""
    set_context(SYSTEM)


def make_device() -> Device:
    tenant = Tenant.objects.create(name="A")
    account = ProviderAccount.objects.create(
        tenant=tenant, provider="viessmann", refresh_token_enc=b"v1|x"
    )
    return Device.objects.create(
        tenant=tenant,
        provider_account=account,
        provider="viessmann",
        external_ids={"installationId": "1", "gatewaySerial": "g", "deviceId": "0"},
        display_name="Pompa",
    )


def feature(
    name: str,
    props: dict[str, tuple[str, object, str | None]],
    *,
    enabled: bool = True,
    ts: str | None = "2026-09-03T10:00:00Z",
) -> Feature:
    return Feature(
        name=name,
        enabled=enabled,
        ready=True,
        properties={
            p: PropertyDef(name=p, type=t, unit=u, value=v, ts_device=ts)  # type: ignore[arg-type]
            for p, (t, v, u) in props.items()
        },
        commands={
            "setTemperature": CommandDef(
                name="setTemperature",
                executable=True,
                params={
                    "targetTemperature": ParamDef(
                        "targetTemperature", "number", True, {"min": 10, "max": 30, "stepping": 1}
                    )
                },
                uri="https://api/x/commands/setTemperature",
            )
        }
        if name.endswith("temperature")
        else {},
        raw={},
    )


@pytest.mark.django_db
def test_first_ingest_creates_definitions_latest_and_history() -> None:
    device = make_device()
    stats = ingest(
        device,
        [
            feature(
                "heating.circuits.0.sensors.temperature.supply",
                {"value": ("number", 41.5, "celsius")},
            ),
            feature("heating.dhw.temperature", {"value": ("number", 50, "celsius")}),
            feature(
                "heating.circuits.0.heating.schedule",
                {"active": ("boolean", True, None), "entries": ("schedule", {"mon": []}, None)},
            ),
            feature("heating.disabled", {"value": ("number", 1, None)}, enabled=False),
        ],
    )
    assert stats.definitions_created == 4 and stats.latest_upserted == 4
    assert stats.history_rows == 3 and stats.json_history_rows == 1
    defs = {d.feature_name: d for d in FeatureDefinition.objects.filter(device=device)}
    assert defs["heating.circuits.0.sensors.temperature.supply"].group_key == "circuits.0"
    assert defs["heating.dhw.temperature"].commands_schema["setTemperature"]["isExecutable"] is True
    assert defs["heating.dhw.temperature"].command_uris == {
        "setTemperature": "https://api/x/commands/setTemperature"
    }
    assert defs["heating.disabled"].is_enabled is False
    assert not FeatureLatest.objects.filter(feature_name="heating.disabled").exists()
    latest = FeatureLatest.objects.get(feature_name="heating.dhw.temperature")
    assert latest.value_num == 50.0 and latest.unit == "celsius" and latest.ts_device is not None
    assert FeatureJsonHistory.objects.get().value_json == {"mon": []}


@pytest.mark.django_db
def test_history_written_on_change_or_after_one_hour() -> None:
    device = make_device()
    t0 = timezone.now() - timedelta(hours=2)

    def f(v: float) -> list[Feature]:
        return [feature("heating.dhw.temperature", {"value": ("number", v, "celsius")})]

    ingest(device, f(50), polled_at=t0)
    ingest(device, f(50), polled_at=t0 + timedelta(minutes=10))  # unchanged, < 1 h → no row
    assert FeatureValue.objects.count() == 1
    ingest(device, f(51), polled_at=t0 + timedelta(minutes=20))  # changed → row
    assert FeatureValue.objects.count() == 2
    ingest(device, f(51), polled_at=t0 + timedelta(minutes=90))  # unchanged but ≥ 1 h → row
    assert FeatureValue.objects.count() == 3
    latest = FeatureLatest.objects.get()
    assert latest.value_num == 51.0 and latest.last_history_at == t0 + timedelta(minutes=90)

    # JSON: only on hash change
    def s(entries: dict[str, list[int]]) -> list[Feature]:
        return [feature("x.schedule", {"entries": ("schedule", entries, None)})]

    ingest(device, s({"mon": [1]}))
    ingest(device, s({"mon": [1]}))
    ingest(device, s({"mon": [2]}))
    assert FeatureJsonHistory.objects.filter(feature_name="x.schedule").count() == 2


@pytest.mark.django_db
def test_definition_updates_and_disabled_feature_keeps_latest_untouched() -> None:
    device = make_device()
    ingest(device, [feature("a.b", {"v": ("number", 1, None)})])
    ingest(device, [feature("a.b", {"v": ("number", 2, None), "w": ("string", "x", None)})])
    d = FeatureDefinition.objects.get(feature_name="a.b")
    assert set(d.properties_schema) == {"v", "w"}
    ingest(device, [feature("a.b", {"v": ("number", 3, None)}, enabled=False)])
    assert FeatureLatest.objects.get(property_name="v").value_num == 2.0  # untouched
    assert FeatureDefinition.objects.get(feature_name="a.b").is_enabled is False


@pytest.mark.django_db
def test_status_transitions_and_history() -> None:
    device = make_device()
    assert status.mark_online(device) is True
    assert status.mark_online(device) is False  # no duplicate history rows
    assert status.mark_offline(device, "GATEWAY_OFFLINE") is True
    assert status.mark_online(device) is True
    assert status.record_error(device, "boom") is False
    assert status.record_error(device, "boom") is False
    assert status.record_error(device, "boom") is True  # third in a row → error
    device.refresh_from_db()
    assert device.status == DeviceStatus.ERROR and device.consecutive_errors == 3
    rows = list(DeviceStatusHistory.objects.filter(device=device).order_by("since"))
    assert [r.status for r in rows] == ["online", "offline", "online", "error"]
    assert all(r.until is not None for r in rows[:-1]) and rows[-1].until is None


@pytest.mark.django_db
def test_stale_device_goes_offline_after_three_intervals() -> None:
    device = make_device()
    status.mark_online(device, at=timezone.now() - timedelta(seconds=1000))
    assert status.check_stale(device, interval_s=400) is False  # 1000 s < 3x400
    assert status.check_stale(device, interval_s=300) is True  # 1000 s > 3x300 -> offline
    device.refresh_from_db()
    assert device.status == DeviceStatus.OFFLINE
