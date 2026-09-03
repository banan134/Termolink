"""History queries for charts and exports (docs/04 §history, docs/09 §Wykresy, docs/10 §CSV).

- raw / 1h / 1d with automatic resolution (≤ 48 h raw, ≤ 90 d 1h, else 1d)
- raw series above `max_points` are downsampled with LTTB (shape-preserving)
- gaps = device offline periods overlapping the range (device_status_history)
- stats: min/max with timestamps, avg, last, count, availability_pct, delta for counters
- markers: verified commands (stage 4) — empty list until then
"""

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import connection
from django.utils import timezone

from apps.core.exceptions import ApiError

from .models import Device, DeviceStatusHistory, FeatureLatest

AUTO_RAW_MAX = timedelta(hours=48)
AUTO_1H_MAX = timedelta(days=90)
MAX_RANGE = timedelta(days=5 * 366)
COUNTER_UNITS = {"kilowattHour", "cubicMeter", "hour", "kilowattHour/year"}
_WHERE = (
    "device_id = %s AND feature_name = %s AND property_name = %s "
    "AND ts_polled >= %s AND ts_polled < %s AND value_num IS NOT NULL"
)


def auto_resolution(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= AUTO_RAW_MAX:
        return "raw"
    if span <= AUTO_1H_MAX:
        return "1h"
    return "1d"


def validate_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ApiError(
            "validation_error",
            "Zakres `from` musi być wcześniejszy niż `to`.",
            fields={"from": ["from >= to"]},
        )
    if end - start > MAX_RANGE:
        raise ApiError(
            "validation_error", "Maksymalny zakres to 5 lat.", fields={"to": ["zakres > 5 lat"]}
        )


def lttb(points: list[tuple[datetime, float]], threshold: int) -> list[tuple[datetime, float]]:
    """Largest-Triangle-Three-Buckets downsampling (keeps peaks, unlike striding)."""
    n = len(points)
    if threshold >= n or threshold < 3:
        return points
    xs = [p[0].timestamp() for p in points]
    ys = [p[1] for p in points]
    sampled = [points[0]]
    bucket = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        r0 = int((i + 1) * bucket) + 1
        r1 = min(int((i + 2) * bucket) + 1, n)
        avg_x = sum(xs[r0:r1]) / max(1, r1 - r0)
        avg_y = sum(ys[r0:r1]) / max(1, r1 - r0)
        s0 = int(i * bucket) + 1
        s1 = min(int((i + 1) * bucket) + 1, n)
        best, best_area = s0, -1.0
        for j in range(s0, s1):
            area = abs((xs[a] - avg_x) * (ys[j] - ys[a]) - (xs[a] - xs[j]) * (avg_y - ys[a]))
            if area > best_area:
                best, best_area = j, area
        sampled.append(points[best])
        a = best
    sampled.append(points[-1])
    return sampled


@dataclass
class Series:
    device: Device
    feature: str
    prop: str


def gaps_for(device: Device, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = DeviceStatusHistory.objects.filter(
        device=device, status="offline", since__lt=end
    ).filter(until__isnull=True) | DeviceStatusHistory.objects.filter(
        device=device, status="offline", since__lt=end, until__gt=start
    )
    out = []
    for r in rows.order_by("since"):
        out.append({"from": max(r.since, start), "to": min(r.until or end, end)})
    return out


def _availability(gaps: list[dict[str, Any]], start: datetime, end: datetime) -> float:
    span = (end - start).total_seconds()
    offline = sum((g["to"] - g["from"]).total_seconds() for g in gaps)
    return round(100.0 * max(0.0, span - offline) / span, 1) if span > 0 else 100.0


def series(
    s: Series,
    *,
    start: datetime,
    end: datetime,
    resolution: str | None,
    max_points: int = 2000,
    include_gaps: bool = True,
) -> dict[str, Any]:
    validate_range(start, end)
    resolution = resolution or auto_resolution(start, end)
    latest = FeatureLatest.objects.filter(
        device=s.device, feature_name=s.feature, property_name=s.prop
    ).first()
    unit = latest.unit if latest else None
    params: list[Any] = [s.device.id, s.feature, s.prop, start, end]
    points: list[dict[str, Any]]
    with connection.cursor() as cursor:
        if resolution == "raw":
            cursor.execute(
                f"SELECT ts_polled, value_num FROM feature_values_rls WHERE {_WHERE} "  # noqa: S608
                "ORDER BY ts_polled",
                params,
            )
            raw = [(ts, float(v)) for ts, v in cursor.fetchall()]
            downsampled = len(raw) > max_points
            raw = lttb(raw, max_points) if downsampled else raw
            points = [{"ts": ts, "value": v} for ts, v in raw]
        else:
            bucket = "1 hour" if resolution == "1h" else "1 day"
            cursor.execute(  # noqa: S608 — constant WHERE, bound params
                "SELECT time_bucket(%s::interval, ts_polled) AS b, min(value_num), avg(value_num), "  # noqa: S608
                "max(value_num), last(value_num, ts_polled), count(value_num) "
                f"FROM feature_values_rls WHERE {_WHERE} GROUP BY b ORDER BY b",  # noqa: S608
                [bucket, *params],
            )
            downsampled = False
            points = [
                {"ts": b, "min": mn, "avg": av, "max": mx, "last": la, "count": c}
                for b, mn, av, mx, la, c in cursor.fetchall()
            ]
    gaps = gaps_for(s.device, start, end) if include_gaps else []
    stats = None
    if points:
        key = "value" if resolution == "raw" else "avg"
        values = [(p["ts"], float(p[key])) for p in points]
        lo = min(values, key=lambda x: x[1])
        hi = max(values, key=lambda x: x[1])
        first = values[0][1]
        last = points[-1]["value"] if resolution == "raw" else points[-1]["last"]
        stats = {
            "min": {"ts": lo[0], "value": lo[1]},
            "max": {"ts": hi[0], "value": hi[1]},
            "avg": sum(v for _, v in values) / len(values),
            "last": last,
            "count": sum(int(p.get("count", 1)) for p in points),
            "availability_pct": _availability(gaps, start, end),
        }
        if unit in COUNTER_UNITS or ".statistics" in s.feature or "consumption" in s.feature:
            stats["delta"] = round(float(last) - first, 3) if last is not None else None
    return {
        "device_id": str(s.device.id),
        "device_name": s.device.display_name,
        "feature": s.feature,
        "property": s.prop,
        "unit": unit,
        "resolution": resolution,
        "downsampled": downsampled,
        "from": start,
        "to": end,
        "points": points,
        "gaps": gaps,
        "stats": stats,
        "markers": markers_for(s, start, end),
    }


def markers_for(s: Series, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """docs/09: verified commands on the timeline — "22 °C → 24 °C, Jan Kowalski"."""
    from apps.control.models import Command, CommandStatus

    out = []
    for c in Command.objects.filter(
        device=s.device,
        feature_name=s.feature,
        status=CommandStatus.VERIFIED,
        verified_at__gte=start,
        verified_at__lt=end,
    ).select_related("user"):
        before = (c.value_before or {}).get(s.prop)
        after = next(iter((c.value_after or {}).values()), None)
        who = c.user.email if c.user else "operator"
        out.append({"ts": c.verified_at, "type": "command", "label": f"{before} → {after}, {who}"})
    return out


def to_csv(result: dict[str, Any]) -> str:
    """docs/10: UTF-8 with BOM, `;` separator, Polish header."""
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(["czas", "urządzenie", "cecha", "właściwość", "wartość", "jednostka"])
    raw = result["resolution"] == "raw"
    for p in result["points"]:
        value = p["value"] if raw else p["avg"]
        ts = p["ts"].isoformat() if hasattr(p["ts"], "isoformat") else str(p["ts"])
        writer.writerow(
            [
                ts,
                result["device_name"],
                result["feature"],
                result["property"],
                f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else value,
                result["unit"] or "",
            ]
        )
    return buf.getvalue()


def default_range(end: datetime | None = None) -> tuple[datetime, datetime]:
    end = end or timezone.now()
    return end - timedelta(days=7), end
