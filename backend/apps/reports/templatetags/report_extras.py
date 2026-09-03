from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django import template

register = template.Library()

UNITS = {
    "celsius": "°C",
    "kelvin": "K",
    "percent": "%",
    "bar": "bar",
    "kilowattHour": "kWh",
    "kilowatt": "kW",
    "watt": "W",
    "hour": "h",
    "hours": "h",
    "minute": "min",
    "cubicMeter": "m³",
    "liter": "l",
    "literPerHour": "l/h",
}


@register.filter
def unit_pl(unit: str | None) -> str:
    return UNITS.get(unit or "", unit or "")


@register.filter
def num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


@register.filter
def local(value: datetime | None, tz: str) -> str:
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(tz)).strftime("%d.%m.%Y %H:%M")


@register.filter
def duration(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h {seconds % 3600 // 60} min"
    return f"{seconds // 86400} d {seconds % 86400 // 3600} h"


@register.filter
def kv(value: dict[str, Any] | None) -> str:
    if not value:
        return "—"
    return ", ".join(f"{k}: {num(v) if isinstance(v, float) else v}" for k, v in value.items())
