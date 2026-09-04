"""Period-over-period insights for a device (docs/09 §Karta urządzenia — „Co się zmieniło”).

Compares the last 7 days (or 30) with the previous window using the 1h aggregates through
`history.series`; counters report increments (reset-safe), sensors report averages, plus
availability. Pure read from the database — never touches the provider API (docs/00)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from apps.devices import history, labels
from apps.devices.grouping import group_key
from apps.devices.models import Device, FeatureLatest

PERIODS = {"week": 7, "month": 30}
COUNTER_HINTS = ("hours", "starts", "consumption", "energy", "statistics")
MAX_SENSORS = 6
MAX_COUNTERS = 6


@dataclass
class Window:
    start: datetime
    end: datetime


def _windows(period: str, now: datetime) -> tuple[Window, Window]:
    days = PERIODS.get(period, 7)
    current = Window(now - timedelta(days=days), now)
    previous = Window(current.start - timedelta(days=days), current.start)
    return current, previous


def _counter_delta(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    total = 0.0
    for a, b in zip(values, values[1:], strict=False):
        if b >= a:
            total += b - a
        elif b < a * 0.5:
            total += b
    return round(total, 2)


def _series_values(device: Device, feature: str, prop: str, w: Window, key: str) -> list[float]:
    s = history.series(
        history.Series(device=device, feature=feature, prop=prop),
        start=w.start,
        end=w.end,
        resolution="1h",
        max_points=5000,
        include_gaps=False,
    )
    return [float(p[key]) for p in s["points"] if p.get(key) is not None]


def _candidates(
    device: Device,
) -> tuple[list[tuple[str, str, str | None]], list[tuple[str, str, str | None]]]:
    rows = list(
        FeatureLatest.objects.filter(device=device, value_num__isnull=False).values_list(
            "feature_name", "property_name", "unit"
        )
    )
    resolved = labels.resolve_many(sorted({f for f, _, _ in rows}))
    counters, sensors = [], []
    for feature, prop, unit in rows:
        is_counter = unit in history.COUNTER_UNITS or any(h in feature for h in COUNTER_HINTS)
        label = resolved.get(feature)
        if is_counter:
            counters.append((feature, prop, unit))
        elif group_key(feature) == "sensors" or (label is not None and label.highlight):
            sensors.append((feature, prop, unit))

    # stable, deterministic order: highlighted first, then by name
    def _rank(item: tuple[str, str, str | None]) -> tuple[bool, str]:
        label = resolved.get(item[0])
        return (not (label is not None and label.highlight), item[0])

    sensors.sort(key=_rank)
    counters.sort(key=lambda x: x[0])
    return counters[:MAX_COUNTERS], sensors[:MAX_SENSORS]


def compute(device: Device, *, period: str = "week", now: datetime | None = None) -> dict[str, Any]:
    now = now or timezone.now()
    cur, prev = _windows(period, now)
    counters, sensors = _candidates(device)
    resolved = labels.resolve_many(sorted({f for f, _, _ in counters + sensors}))
    items: list[dict[str, Any]] = []
    for feature, prop, unit in counters:
        c = _counter_delta(_series_values(device, feature, prop, cur, "last"))
        p = _counter_delta(_series_values(device, feature, prop, prev, "last"))
        if c is None and p is None:
            continue
        items.append(_item("counter", feature, prop, unit, resolved, c, p))
    for feature, prop, unit in sensors:
        cv = _series_values(device, feature, prop, cur, "avg")
        pv = _series_values(device, feature, prop, prev, "avg")
        c = round(sum(cv) / len(cv), 2) if cv else None
        p = round(sum(pv) / len(pv), 2) if pv else None
        if c is None and p is None:
            continue
        items.append(_item("average", feature, prop, unit, resolved, c, p))
    gaps_cur = history.gaps_for(device, cur.start, cur.end)
    gaps_prev = history.gaps_for(device, prev.start, prev.end)
    items.append(
        {
            "kind": "availability",
            "feature": None,
            "property": None,
            "label": "Dostępność",
            "unit": "percent",
            "current": history._availability(gaps_cur, cur.start, cur.end),
            "previous": history._availability(gaps_prev, prev.start, prev.end),
        }
    )
    for it in items:
        c, p = it["current"], it["previous"]
        it["delta"] = round(c - p, 2) if c is not None and p is not None else None
        it["delta_pct"] = (
            round(100 * (c - p) / abs(p), 1) if c is not None and p not in (None, 0) else None
        )
    return {
        "period": period,
        "days": PERIODS.get(period, 7),
        "current": {"from": cur.start, "to": cur.end},
        "previous": {"from": prev.start, "to": prev.end},
        "items": items,
    }


def _item(
    kind: str,
    feature: str,
    prop: str,
    unit: str | None,
    resolved: dict[str, Any],
    c: float | None,
    p: float | None,
) -> dict[str, Any]:
    label = resolved.get(feature)
    return {
        "kind": kind,
        "feature": feature,
        "property": prop,
        "label": label.label_pl if label else feature,
        "unit": unit,
        "current": c,
        "previous": p,
    }
