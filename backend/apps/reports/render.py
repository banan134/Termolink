"""CSV / HTML / PDF rendering (docs/10 §Formaty). Charts are drawn as inline SVG here — no
matplotlib, no headless browser (decision for stage 5: the report chart is a simple line with a
min–max band, which a 60-line renderer covers; ECharts stays in the browser)."""

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.template.loader import render_to_string

from apps.tenants.models import Tenant

from .models import ReportType

BOM = "﻿"


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


def _local(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# --- CSV -----------------------------------------------------------------------------------------


def render_csv(data: dict[str, Any]) -> str:
    buf = io.StringIO()
    buf.write(BOM)
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    tz = data["tenant"]["timezone"]
    rtype = data["report_type"]
    if rtype in (ReportType.OPERATION, ReportType.ENERGY):
        w.writerow(["czas", "urządzenie", "cecha", "właściwość", "wartość", "jednostka"])
        raw = data["resolution"] == "raw"
        for d in data["devices"]:
            for s in d["series"]:
                for p in s["points"]:
                    value = p["value"] if raw else p["avg"]
                    w.writerow(
                        [
                            _local(p["ts"], tz),
                            d["name"],
                            s["feature"],
                            s["property"],
                            _fmt(value),
                            s["unit"] or "",
                        ]
                    )
    elif rtype == ReportType.AVAILABILITY:
        w.writerow(["urządzenie", "dostępność %", "przerwa od", "przerwa do", "sekundy"])
        for d in data["devices"]:
            if not d.get("offline"):
                w.writerow([d["name"], _fmt(d["availability_pct"]), "", "", ""])
            for g in d.get("offline", []):
                w.writerow(
                    [
                        d["name"],
                        _fmt(d["availability_pct"]),
                        _local(g["from"], tz),
                        _local(g["to"], tz),
                        g["seconds"],
                    ]
                )
    else:
        w.writerow(
            ["czas", "urządzenie", "cecha", "komenda", "przed", "po", "status", "użytkownik"]
        )
        for d in data["devices"]:
            for c in d.get("commands", []):
                w.writerow(
                    [
                        _local(c["created_at"], tz),
                        d["name"],
                        c["feature"],
                        c["command"],
                        _fmt_dict(c["value_before"]),
                        _fmt_dict(c["value_after"]),
                        c["status"],
                        c["user"] or "",
                    ]
                )
    return buf.getvalue()


def _fmt_dict(v: dict[str, Any] | None) -> str:
    if not v:
        return ""
    return ", ".join(f"{k}={_fmt(val)}" for k, val in v.items())


# --- SVG chart -----------------------------------------------------------------------------------

W, H, PAD_L, PAD_R, PAD_T, PAD_B = 720, 220, 48, 12, 10, 28


def svg_chart(series: dict[str, Any], start: datetime, end: datetime, tz: str) -> str:
    """Line of avg/value with a min–max band for aggregated buckets; 5 Y ticks, 6 X ticks."""
    pts = series["points"]
    raw = "value" in (pts[0] if pts else {})
    xs = [p["ts"] for p in pts]
    ys = [float(p["value"] if raw else p["avg"]) for p in pts]
    if not ys:
        return (
            f'<svg viewBox="0 0 {W} {H}" class="chart"><text x="{W / 2}" y="{H / 2}" '
            'text-anchor="middle" class="muted">brak danych</text></svg>'
        )
    lo_v = min([float(p["min"]) for p in pts] if not raw else ys)
    hi_v = max([float(p["max"]) for p in pts] if not raw else ys)
    if hi_v == lo_v:
        hi_v, lo_v = hi_v + 1, lo_v - 1
    span_y = hi_v - lo_v
    lo_v, hi_v = lo_v - span_y * 0.05, hi_v + span_y * 0.05
    t0, t1 = start.timestamp(), end.timestamp()

    def sx(t: datetime) -> float:
        return PAD_L + (t.timestamp() - t0) / max(t1 - t0, 1) * (W - PAD_L - PAD_R)

    def sy(v: float) -> float:
        return PAD_T + (hi_v - v) / (hi_v - lo_v) * (H - PAD_T - PAD_B)

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    for i in range(5):
        v = lo_v + (hi_v - lo_v) * i / 4
        y = sy(v)
        parts.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{PAD_L - 4}" y="{y + 3:.1f}" text-anchor="end" class="tick">'
            f"{_fmt(round(v, 2))}</text>"
        )
    zone = ZoneInfo(tz)
    long_range = (end - start).total_seconds() > 48 * 3600
    for i in range(6):
        t = start + (end - start) * i / 5
        x = sx(t)
        label = t.astimezone(zone).strftime("%d.%m" if long_range else "%H:%M")
        parts.append(
            f'<text x="{x:.1f}" y="{H - 8}" text-anchor="middle" class="tick">{label}</text>'
        )
    if not raw:
        upper = " ".join(
            f"{sx(x):.1f},{sy(float(p['max'])):.1f}" for x, p in zip(xs, pts, strict=False)
        )
        lower = " ".join(
            f"{sx(x):.1f},{sy(float(p['min'])):.1f}"
            for x, p in reversed(list(zip(xs, pts, strict=False)))
        )
        parts.append(f'<polygon points="{upper} {lower}" class="band"/>')
    line = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(xs, ys, strict=False))
    parts.append(f'<polyline points="{line}" class="line"/>')
    for m in series.get("markers") or []:
        x = sx(m["ts"])
        parts.append(
            f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" y2="{H - PAD_B}" class="marker"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --- HTML / PDF ----------------------------------------------------------------------------------


def render_html(data: dict[str, Any], tenant: Tenant) -> str:
    tz = data["tenant"]["timezone"]
    logo_url = None
    if tenant.logo_path:
        candidate = Path(settings.MEDIA_ROOT) / tenant.logo_path
        if candidate.exists():
            logo_url = candidate.as_uri()
    devices = []
    for d in data["devices"]:
        charts = [
            {**s, "svg": svg_chart(s, data["from"], data["to"], tz), "stats": s["stats"]}
            for s in d.get("series", [])
        ]
        devices.append({**d, "charts": charts})
    context = {
        "data": data,
        "devices": devices,
        "tenant": tenant,
        "logo_url": logo_url,
        "tz": tz,
        "type_label": ReportType(data["report_type"]).label,
        "from_local": _local(data["from"], tz),
        "to_local": _local(data["to"], tz),
        "generated_local": _local(data["generated_at"], tz),
        "resolution_label": {
            "raw": "dane surowe",
            "1h": "średnie godzinowe",
            "1d": "średnie dobowe",
        }.get(data["resolution"], data["resolution"]),
    }
    return render_to_string("reports/report.html", context)


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML  # heavy import, only when a PDF is actually rendered

    return bytes(HTML(string=html, base_url=str(settings.MEDIA_ROOT)).write_pdf())
