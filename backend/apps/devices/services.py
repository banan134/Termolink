"""Device services — docs/04 §Urządzenia, docs/07 §can_control. Views call these."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.services import audit
from apps.core.exceptions import ApiError
from apps.ingest import queue
from apps.ingest.models import Job
from apps.providers import budget
from apps.providers.models import CallKind, ProviderAccount
from apps.tenants.models import Tenant, TenantMembership

from .grouping import group_sort_key
from .models import (
    Device,
    DeviceMode,
    DeviceStatus,
    DeviceStatusHistory,
    DiscoveredDevice,
    FeatureDefinition,
    FeatureLatest,
)

TENANT_ADMIN_FIELDS = ("display_name", "description", "location_text", "lat", "lon")
OPERATOR_FIELDS = (*TENANT_ADMIN_FIELDS, "mode", "poll_interval_s", "commands_per_hour_limit")

# docs/04: fallback highlights when no feature_labels.highlight (stage 3)
HIGHLIGHT_FALLBACK = [
    ("heating.sensors.temperature.outside", "value", "Temp. zewnętrzna"),
    ("heating.circuits.0.sensors.temperature.supply", "value", "Zasilanie obiegu 1"),
    ("heating.dhw.sensors.temperature.hotWaterStorage", "value", "Ciepła woda"),
    ("heating.dhw.temperature.main", "value", "CWU zadana"),
]


def get_device_or_404(
    tenant: Tenant, device_id: str | UUID, *, include_archived: bool = False
) -> Device:
    try:
        qs = Device.objects.select_related("provider_account", "tenant")
        device = qs.get(id=UUID(str(device_id)), tenant=tenant)
    except (Device.DoesNotExist, ValueError) as exc:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404) from exc
    if device.archived_at and not include_archived:
        raise ApiError("not_found", "Nie znaleziono.", status_code=404)
    return device


# --- cards / details ---------------------------------------------------------------------------


def highlights_for(devices: list[Device]) -> dict[UUID, list[dict[str, Any]]]:
    wanted = [(f, p) for f, p, _ in HIGHLIGHT_FALLBACK]
    rows = FeatureLatest.objects.filter(device__in=devices).filter(
        feature_name__in=[f for f, _ in wanted]
    )
    by_device: dict[UUID, dict[tuple[str, str], FeatureLatest]] = {}
    for row in rows:
        by_device.setdefault(row.device_id, {})[(row.feature_name, row.property_name)] = row
    result: dict[UUID, list[dict[str, Any]]] = {}
    for device in devices:
        items = []
        for feature, prop, label in HIGHLIGHT_FALLBACK:
            hit: FeatureLatest | None = by_device.get(device.id, {}).get((feature, prop))
            if hit is not None and hit.value_num is not None:
                items.append(
                    {
                        "feature": feature,
                        "property": prop,
                        "label": label,
                        "value": hit.value_num,
                        "unit": hit.unit,
                    }
                )
        result[device.id] = items[:3]
    return result


def card(device: Device, highlights: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "display_name": device.display_name,
        "model": device.model,
        "location_text": device.location_text,
        "description": device.description,
        "mode": device.mode,
        "status": device.status,
        "status_since": device.status_since,
        "status_detail": device.status_detail,
        "last_seen_at": device.last_seen_at,
        "last_polled_at": device.last_polled_at,
        "next_poll_at": device.next_poll_at,
        "highlights": highlights,
    }


def can_control(user: User, device: Device) -> tuple[bool, list[str]]:
    """docs/07 §Kto może wykonać komendę — conditions 1–4 and 6 (5 arrives with commands)."""
    reasons: list[str] = []
    if device.mode != DeviceMode.CONTROL:
        reasons.append("device_read_only")
    if not device.tenant.control_allowed:
        reasons.append("tenant_control_blocked")
    if user.role == Role.SUPERADMIN:
        pass
    elif user.role == Role.TECHNICIAN:
        if not TenantMembership.objects.filter(
            user=user, tenant=device.tenant, can_control=True
        ).exists():
            reasons.append("operator_no_control_permission")
    elif user.role == Role.TENANT_ADMIN:
        if not user.totp_enabled:
            reasons.append("totp_required")
    else:
        reasons.append("role_not_allowed")
    if device.status != DeviceStatus.ONLINE:
        reasons.append("device_not_online")
    if budget.available_for_reserve(device.provider_account) < 2:
        reasons.append("budget_reserve_exhausted")
    return (not reasons, reasons)


def details(user: User, device: Device) -> dict[str, Any]:
    ok, reasons = can_control(user, device)
    payload = card(device, highlights_for([device]).get(device.id, []))
    payload.update(
        {
            "provider": device.provider,
            "provider_account_id": str(device.provider_account_id),
            "external_ids": device.external_ids,
            "serial": device.serial,
            "lat": float(device.lat) if device.lat is not None else None,
            "lon": float(device.lon) if device.lon is not None else None,
            "poll_interval_s": device.poll_interval_s,
            "effective_interval_s": budget.interval_for(
                device.provider_account,
                Device.objects.filter(
                    provider_account=device.provider_account, archived_at__isnull=True
                ).count(),
                device.poll_interval_s,
            ),
            "commands_per_hour_limit": device.commands_per_hour_limit,
            "budget": budget.status(device.provider_account).as_dict(),
            "account_status": device.provider_account.status,
            "capabilities": {"can_control": ok, "reasons": reasons},
            "created_at": device.created_at,
        }
    )
    return payload


# --- create / update / archive ----------------------------------------------------------------


def create_device(
    request: HttpRequest, *, actor: User, tenant: Tenant, data: dict[str, Any]
) -> Device:
    try:
        account = ProviderAccount.objects.get(id=data["provider_account_id"], tenant=tenant)
    except ProviderAccount.DoesNotExist as exc:
        raise ApiError(
            "validation_error",
            "Nieprawidłowe konto producenta.",
            fields={"provider_account_id": ["Nie znaleziono."]},
        ) from exc
    ids = data["external_ids"]
    discovered = DiscoveredDevice.objects.filter(
        provider_account=account,
        installation_id=ids.get("installationId"),
        gateway_serial=ids.get("gatewaySerial"),
        device_id=ids.get("deviceId"),
    ).first()
    if Device.objects.filter(
        provider_account=account,
        external_ids__installationId=ids.get("installationId"),
        external_ids__gatewaySerial=ids.get("gatewaySerial"),
        external_ids__deviceId=ids.get("deviceId"),
        archived_at__isnull=True,
    ).exists():
        raise ApiError("device_exists", "To urządzenie jest już dodane.", status_code=409)
    with transaction.atomic():
        device = Device.objects.create(
            tenant=tenant,
            provider_account=account,
            provider=account.provider,
            external_ids={k: str(ids[k]) for k in ("installationId", "gatewaySerial", "deviceId")},
            model=(
                discovered.model if discovered and discovered.model else data.get("model") or ""
            ),
            display_name=data["display_name"],
            description=data.get("description"),
            location_text=data.get("location_text"),
            lat=data.get("lat"),
            lon=data.get("lon"),
            mode=data.get("mode") or DeviceMode.READ,
            poll_interval_s=data.get("poll_interval_s"),
            next_poll_at=timezone.now() + timedelta(seconds=60),  # scheduler takes over
        )
        job = queue.enqueue(
            "poll",
            {"device_id": str(device.id)},
            tenant=tenant,
            provider_account_id=account.id,
            created_by=actor,
            priority=50,
        )
    audit(
        "device.created",
        request=request,
        user=actor,
        tenant=tenant,
        target=device,
        details={
            "external_ids": device.external_ids,
            "mode": device.mode,
            "first_poll_job": str(job.public_id),
        },
    )
    spread_next_polls(account)
    return device


def spread_next_polls(account: ProviderAccount) -> None:
    """docs/06: stagger next_poll_at so reads are evenly spread, not batched."""
    devices = list(
        Device.objects.filter(provider_account=account, archived_at__isnull=True).order_by(
            "created_at"
        )
    )
    n = len(devices)
    if n < 2:
        return
    interval = budget.auto_interval_s(account, n)
    base = timezone.now()
    for i, device in enumerate(devices):
        device.next_poll_at = base + timedelta(seconds=interval * i / n)
        device.save(update_fields=["next_poll_at", "updated_at"])


def update_device(
    request: HttpRequest, *, actor: User, device: Device, data: dict[str, Any]
) -> Device:
    from apps.accounts.services import require_reauth

    allowed = OPERATOR_FIELDS if actor.is_operator else TENANT_ADMIN_FIELDS
    changes = {k: v for k, v in data.items() if k in allowed}
    forbidden_fields = sorted(set(data) - set(allowed))
    if forbidden_fields:
        raise ApiError(
            "forbidden", "Brak uprawnień do zmiany: " + ", ".join(forbidden_fields), status_code=403
        )
    if "mode" in changes and changes["mode"] != device.mode:
        require_reauth(request)  # docs/07: mode change needs password + TOTP
        old_mode = device.mode
        device.mode = changes["mode"]
        audit(
            "device.mode.changed",
            request=request,
            user=actor,
            tenant=device.tenant,
            target=device,
            details={"from": old_mode, "to": device.mode},
        )
    for key, value in changes.items():
        if key != "mode":
            setattr(device, key, value)
    device.save()
    if set(changes) - {"mode"}:
        audit(
            "device.updated",
            request=request,
            user=actor,
            tenant=device.tenant,
            target=device,
            details={"fields": sorted(set(changes) - {"mode"})},
        )
    return device


def archive_device(request: HttpRequest, *, actor: User, device: Device) -> None:
    device.archived_at = timezone.now()
    device.save(update_fields=["archived_at", "updated_at"])
    Job.objects.filter(kind="poll", status="queued", payload__device_id=str(device.id)).update(
        status="failed", last_error="device archived"
    )
    audit("device.archived", request=request, user=actor, tenant=device.tenant, target=device)


def refresh_now(request: HttpRequest, *, actor: User, device: Device) -> Job:
    """„Odśwież teraz” — from the reserve budget; 429 when the reserve is gone (docs/04)."""
    account = device.provider_account
    if budget.available_for_reserve(account) < 1:
        raise ApiError(
            "budget_reserve_exhausted",
            "Rezerwa budżetu API wyczerpana.",
            status_code=429,
            extra={"retry_at": budget.status(account).reset_at},
        )
    pending = Job.objects.filter(
        kind="poll",
        status__in=["queued", "running"],
        payload__device_id=str(device.id),
        payload__kind="refresh",
    ).first()
    if pending:
        return pending
    audit(
        "device.refresh.requested", request=request, user=actor, tenant=device.tenant, target=device
    )
    return queue.enqueue(
        "poll",
        {"device_id": str(device.id), "kind": CallKind.REFRESH},
        tenant=device.tenant,
        provider_account_id=account.id,
        created_by=actor,
        priority=10,
    )


# --- features / history -----------------------------------------------------------------------


def features(device: Device) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, FeatureLatest]] = {}
    for row in FeatureLatest.objects.filter(device=device):
        latest.setdefault(row.feature_name, {})[row.property_name] = row
    items = []
    for d in FeatureDefinition.objects.filter(device=device):
        props = {}
        for name, schema in d.properties_schema.items():
            lr: FeatureLatest | None = latest.get(d.feature_name, {}).get(name)
            value: Any = None
            if lr is not None:
                value = (
                    lr.value_num
                    if lr.value_num is not None
                    else lr.value_bool
                    if lr.value_bool is not None
                    else lr.value_text
                    if lr.value_text is not None
                    else lr.value_json
                )
            props[name] = {
                "type": schema.get("type"),
                "unit": (lr.unit if lr else schema.get("unit")),
                "value": value,
                "ts_device": lr.ts_device if lr else None,
                "ts_polled": lr.ts_polled if lr else None,
            }
        items.append(
            {
                "feature_name": d.feature_name,
                "label_pl": None,  # feature_labels dictionary arrives in stage 3
                "group_key": d.group_key,
                "is_enabled": d.is_enabled,
                "is_ready": d.is_ready,
                "properties": props,
                "commands": {
                    name: {
                        "executable": c.get("isExecutable", False)
                        and name not in d.unsupported_commands,
                        "params": c.get("params", {}),
                    }
                    for name, c in d.commands_schema.items()
                },
                "unsupported_commands": d.unsupported_commands,
                "last_seen_at": d.last_seen_at,
            }
        )
    items.sort(key=lambda i: (group_sort_key(str(i["group_key"])), str(i["feature_name"])))
    return items


AUTO_RAW_MAX = timedelta(hours=48)
AUTO_1H_MAX = timedelta(days=90)


def auto_resolution(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= AUTO_RAW_MAX:
        return "raw"
    if span <= AUTO_1H_MAX:
        return "1h"
    return "1d"


def history(
    device: Device,
    *,
    feature: str,
    prop: str,
    start: datetime,
    end: datetime,
    resolution: str | None,
    max_points: int = 2000,
) -> dict[str, Any]:
    if end <= start:
        raise ApiError(
            "validation_error",
            "Zakres `from` musi być wcześniejszy niż `to`.",
            fields={"from": ["from >= to"]},
        )
    if end - start > timedelta(days=5 * 366):
        raise ApiError(
            "validation_error", "Maksymalny zakres to 5 lat.", fields={"to": ["zakres > 5 lat"]}
        )
    resolution = resolution or auto_resolution(start, end)
    unit = (
        FeatureLatest.objects.filter(device=device, feature_name=feature, property_name=prop)
        .values_list("unit", flat=True)
        .first()
    )
    where = (
        "device_id = %s AND feature_name = %s AND property_name = %s "
        "AND ts_polled >= %s AND ts_polled < %s AND value_num IS NOT NULL"
    )
    params: list[Any] = [device.id, feature, prop, start, end]
    points: list[dict[str, Any]]
    with connection.cursor() as cursor:
        if resolution == "raw":
            cursor.execute(
                f"SELECT ts_polled, value_num FROM feature_values_rls WHERE {where} "  # noqa: S608
                "ORDER BY ts_polled",
                params,
            )
            points = [{"ts": ts, "value": v} for ts, v in cursor.fetchall()]
            if len(points) > max_points:  # simple stride downsampling; LTTB in stage 3
                step = len(points) / max_points
                points = [points[int(i * step)] for i in range(max_points)]
        else:
            bucket = "1 hour" if resolution == "1h" else "1 day"
            cursor.execute(  # noqa: S608 — `where` is a constant, values are bound params
                "SELECT time_bucket(%s::interval, ts_polled) AS b, min(value_num), avg(value_num), "  # noqa: S608
                "max(value_num), last(value_num, ts_polled), count(value_num) "
                f"FROM feature_values_rls WHERE {where} GROUP BY b ORDER BY b",
                [bucket, *params],
            )
            points = [
                {"ts": b, "min": mn, "avg": av, "max": mx, "last": la, "count": c}
                for b, mn, av, mx, la, c in cursor.fetchall()
            ]
    values = [p["value"] if resolution == "raw" else p["avg"] for p in points]
    stats = None
    if points:
        last = points[-1]["value"] if resolution == "raw" else points[-1]["last"]
        stats = {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "last": last,
            "count": len(points),
        }
    return {
        "feature": feature,
        "property": prop,
        "unit": unit,
        "resolution": resolution,
        "from": start,
        "to": end,
        "points": points,
        "stats": stats,
    }


def status_history(device: Device, limit: int = 200) -> list[dict[str, Any]]:
    return [
        {"status": r.status, "since": r.since, "until": r.until, "detail": r.detail}
        for r in DeviceStatusHistory.objects.filter(device=device).order_by("-since")[:limit]
    ]
