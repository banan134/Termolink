"""Report data — docs/10 §Typy raportów, §Wyliczenia. Pure data; rendering lives in render.py."""

import calendar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.alerts.models import Alert
from apps.control.models import Command
from apps.core.exceptions import ApiError
from apps.devices import history, labels
from apps.devices.grouping import group_key
from apps.devices.models import Device, FeatureLatest
from apps.tenants.models import Tenant

from .models import Period, ReportType

MAX_POINTS = 50_000
MIN_GAP_S = 120
RESET_RATIO = 0.5  # a drop below half of the previous value counts as a counter reset
ENERGY_HINTS = (".statistics", "consumption", "energy", "power.production", "gas")
COUNTER_HINTS = ("hours", "starts", "consumption", "energy", "statistics")


@dataclass
class Params:
    report_type: str
    device_ids: list[UUID]
    start: datetime
    end: datetime
    resolution: str | None = None
    features: list[str] = field(default_factory=list)

    @property
    def effective_resolution(self) -> str:
        return self.resolution or history.auto_resolution(self.start, self.end)


def parse_params(tenant: Tenant, body: dict[str, Any]) -> Params:
    errors: dict[str, list[str]] = {}
    rtype = body.get("report_type")
    if rtype not in ReportType.values:
        errors["report_type"] = ["Nieznany typ raportu."]
    ids: list[UUID] = []
    for raw in body.get("device_ids") or []:
        try:
            ids.append(UUID(str(raw)))
        except ValueError:
            errors["device_ids"] = ["Błędny identyfikator."]
    if not ids:
        errors["device_ids"] = ["Wybierz co najmniej jedno urządzenie."]
    try:
        start = _parse_dt(body.get("from"))
        end = _parse_dt(body.get("to"))
    except ValueError:
        errors["from"] = ["Błędna data."]
        start = end = timezone.now()
    if errors:
        raise ApiError("validation_error", "Błędne parametry raportu.", fields=errors)
    try:
        history.validate_range(start, end)
    except ApiError as exc:
        message = str(exc.detail)
        raise ApiError("validation_error", message, fields={"from": [message]}) from exc
    resolution = body.get("resolution") or None
    if resolution not in (None, "auto", "raw", "1h", "1d"):
        raise ApiError(
            "validation_error", "Błędna rozdzielczość.", fields={"resolution": ["raw/1h/1d/auto"]}
        )
    features = [str(f) for f in (body.get("features") or []) if f]
    params = Params(
        report_type=str(rtype),
        device_ids=ids,
        start=start,
        end=end,
        resolution=None if resolution == "auto" else resolution,
        features=features,
    )
    found = set(Device.objects.filter(tenant=tenant, id__in=ids).values_list("id", flat=True))
    if found != set(ids):
        raise ApiError("not_found", "Nie znaleziono urządzenia.", status_code=404)
    return params


def _parse_dt(value: Any) -> datetime:
    if not value:
        raise ValueError("missing")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def period_range(period: str, tz: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """docs/10 §Harmonogram: the completed previous day/week/month in the tenant's timezone."""
    zone = ZoneInfo(tz)
    local = (now or timezone.now()).astimezone(zone)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == Period.LAST_DAY:
        return today - timedelta(days=1), today
    if period == Period.LAST_WEEK:
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday
    first = today.replace(day=1)
    prev_last = first - timedelta(days=1)
    return prev_last.replace(day=1), first


# --- feature selection -------------------------------------------------------------------------


def default_features(device: Device) -> list[tuple[str, str]]:
    """feature_labels.report_default + every numeric property in group `sensors` (docs/10)."""
    rows = list(
        FeatureLatest.objects.filter(device=device, value_num__isnull=False).values_list(
            "feature_name", "property_name"
        )
    )
    resolved = labels.resolve_many(sorted({f for f, _ in rows}))
    out = []
    for feature, prop in rows:
        label = resolved.get(feature)
        if (label is not None and label.report_default) or group_key(feature) == "sensors":
            out.append((feature, prop))
    return sorted(set(out))


def energy_features(device: Device) -> list[tuple[str, str]]:
    rows = FeatureLatest.objects.filter(device=device, value_num__isnull=False).values_list(
        "feature_name", "property_name"
    )
    return sorted({(f, p) for f, p in rows if any(h in f for h in ENERGY_HINTS)})


def _selected(device: Device, params: Params) -> list[tuple[str, str]]:
    if not params.features:
        return default_features(device)
    out: list[tuple[str, str]] = []
    available = {
        (f, p)
        for f, p in FeatureLatest.objects.filter(
            device=device, value_num__isnull=False
        ).values_list("feature_name", "property_name")
    }
    for item in params.features:
        matches = [(f, p) for f, p in available if item == f or item == f"{f}.{p}"]
        out.extend(matches)
    return sorted(set(out))


# --- calculations (docs/10 §Wyliczenia) ---------------------------------------------------------


def counter_delta(values: list[float]) -> float | None:
    """Increment over the period, robust to counter resets: sum of rising segments."""
    if len(values) < 2:
        return None
    total = 0.0
    for a, b in zip(values, values[1:], strict=False):
        if b >= a:
            total += b - a
        elif b < a * RESET_RATIO:
            # a real reset: the counter restarted from zero and reached b
            total += b
        # a small drop (sensor noise / re-sync) is ignored rather than counted as a reset
    return round(total, 3)


def is_counter(feature: str, unit: str | None) -> bool:
    return (unit in history.COUNTER_UNITS) or any(h in feature for h in COUNTER_HINTS)


def offline_intervals(device: Device, start: datetime, end: datetime) -> list[dict[str, Any]]:
    gaps = history.gaps_for(device, start, end)
    return [
        {**g, "seconds": int((g["to"] - g["from"]).total_seconds())}
        for g in gaps
        if (g["to"] - g["from"]).total_seconds() >= MIN_GAP_S
    ]


def availability_pct(device: Device, start: datetime, end: datetime) -> float:
    gaps = history.gaps_for(device, start, end)
    return history._availability(gaps, start, end)


# --- building -------------------------------------------------------------------------------------


def build(tenant: Tenant, params: Params) -> dict[str, Any]:
    devices = list(
        Device.objects.filter(tenant=tenant, id__in=params.device_ids).order_by("display_name")
    )
    resolution = params.effective_resolution
    out: dict[str, Any] = {
        "report_type": params.report_type,
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "timezone": tenant.timezone,
            "header_text": tenant.report_header_text,
        },
        "from": params.start,
        "to": params.end,
        "resolution": resolution,
        "generated_at": timezone.now(),
        "devices": [],
        "total_points": 0,
    }
    for device in devices:
        entry: dict[str, Any] = {
            "id": str(device.id),
            "name": device.display_name,
            "model": device.model,
            "location": device.location_text,
            "availability_pct": availability_pct(device, params.start, params.end),
            "series": [],
        }
        if params.report_type in (ReportType.OPERATION, ReportType.ENERGY):
            selection = (
                energy_features(device)
                if params.report_type == ReportType.ENERGY
                else _selected(device, params)
            )
            entry["energy_available"] = (
                bool(selection) if params.report_type == ReportType.ENERGY else None
            )
            for feature, prop in selection:
                s = history.series(
                    history.Series(device=device, feature=feature, prop=prop),
                    start=params.start,
                    end=params.end,
                    resolution=resolution,
                    max_points=5000,
                    include_gaps=False,
                )
                out["total_points"] += len(s["points"])
                if out["total_points"] > MAX_POINTS:
                    raise ApiError(
                        "too_many_points",
                        "Raport przekracza 50 000 punktów — zawęź zakres lub zwiększ "
                        "rozdzielczość.",
                        status_code=413,
                    )
                label = labels.resolve(feature)
                counter = is_counter(feature, s["unit"])
                if counter and s["points"]:
                    key = "value" if resolution == "raw" else "last"
                    vals = [float(p[key]) for p in s["points"] if p.get(key) is not None]
                    if s["stats"] is not None:
                        s["stats"]["delta"] = counter_delta(vals)
                entry["series"].append(
                    {
                        "feature": feature,
                        "property": prop,
                        "label": label.label_pl if label else feature,
                        "unit": s["unit"],
                        "counter": counter,
                        "points": s["points"],
                        "stats": s["stats"],
                        "markers": s["markers"],
                    }
                )
        if params.report_type in (ReportType.OPERATION, ReportType.AVAILABILITY):
            entry["offline"] = offline_intervals(device, params.start, params.end)
        if params.report_type == ReportType.AVAILABILITY:
            entry["alerts"] = [
                {
                    "type": a.type,
                    "severity": a.severity,
                    "message": a.message,
                    "opened_at": a.opened_at,
                    "closed_at": a.closed_at,
                }
                for a in Alert.objects.filter(device=device, opened_at__lt=params.end)
                .filter(closed_at__isnull=True)
                .union(
                    Alert.objects.filter(
                        device=device, opened_at__lt=params.end, closed_at__gte=params.start
                    )
                )
                .order_by("-opened_at")[:200]
            ]
        if params.report_type == ReportType.CHANGES:
            entry["commands"] = [
                {
                    "created_at": c.created_at,
                    "feature": c.feature_name,
                    "command": c.command_name,
                    "value_before": c.value_before,
                    "value_after": c.value_after,
                    "status": c.status,
                    "user": c.user.email if c.user else None,
                    "acted_as_operator": c.acted_as_operator,
                }
                for c in Command.objects.filter(
                    device=device, created_at__gte=params.start, created_at__lt=params.end
                )
                .exclude(status__in=["draft", "expired"])
                .select_related("user")
                .order_by("-created_at")[:1000]
            ]
        out["devices"].append(entry)
    return out


def month_name_pl(dt: datetime) -> str:
    names = [
        "styczeń",
        "luty",
        "marzec",
        "kwiecień",
        "maj",
        "czerwiec",
        "lipiec",
        "sierpień",
        "wrzesień",
        "październik",
        "listopad",
        "grudzień",
    ]
    return f"{names[dt.month - 1]} {dt.year}"


__all__ = [
    "Params",
    "build",
    "calendar",
    "counter_delta",
    "default_features",
    "parse_params",
    "period_range",
]
