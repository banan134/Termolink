"""Command parameter validation — docs/05 §Walidacja parametrów komendy (provider-agnostic).

Validates against the *last read* command schema (feature_definitions.commands_schema).
Every rule has an OK and an error test (docs/12).
"""

import math
import re
from typing import Any

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME_RE = re.compile(r"^([01]\d|2[0-4]):[0-5]\d$")
EPS = 1e-9


class ValidationErrors(dict[str, list[str]]):
    def add(self, field: str, message: str) -> None:
        self.setdefault(field, []).append(message)


def validate_params(schema: dict[str, Any], params: dict[str, Any]) -> ValidationErrors:
    """Validate against commands_schema[command] = {"isExecutable", "params": {name: {...}}}."""
    errors = ValidationErrors()
    definitions: dict[str, dict[str, Any]] = schema.get("params") or {}
    for name in params:
        if name not in definitions:
            errors.add(name, "Nieznany parametr.")
    for name, definition in definitions.items():
        if name not in params:
            if definition.get("required", False):
                errors.add(name, "Parametr wymagany.")
            continue
        _validate_value(name, params[name], definition, errors)
    return errors


def _validate_value(
    name: str, value: Any, definition: dict[str, Any], errors: ValidationErrors
) -> None:
    kind = str(definition.get("type", "")).lower()
    constraints: dict[str, Any] = definition.get("constraints") or {}
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            errors.add(name, "Oczekiwano liczby.")
            return
        lo = constraints.get("min")
        hi = constraints.get("max")
        if lo is not None and value < lo - EPS:
            errors.add(name, f"Wartość poniżej minimum ({lo}).")
        if hi is not None and value > hi + EPS:
            errors.add(name, f"Wartość powyżej maksimum ({hi}).")
        step = constraints.get("stepping")
        if step:
            base = lo if lo is not None else 0
            ratio = (value - base) / step
            if abs(ratio - round(ratio)) > EPS:
                errors.add(name, f"Wartość musi być wielokrotnością kroku {step}.")
    elif kind == "string":
        if not isinstance(value, str):
            errors.add(name, "Oczekiwano tekstu.")
            return
        enum = constraints.get("enum")
        if enum is not None and value not in enum:
            errors.add(name, "Wartość spoza dozwolonej listy.")
        max_len = constraints.get("maxLength")
        if max_len is not None and len(value) > max_len:
            errors.add(name, f"Maksymalna długość: {max_len}.")
    elif kind == "boolean":
        if not isinstance(value, bool):
            errors.add(name, "Oczekiwano wartości logicznej.")
    elif kind == "schedule":
        _validate_schedule(name, value, constraints, errors)
    elif kind in ("array", "object"):
        if kind == "array" and not isinstance(value, list):
            errors.add(name, "Oczekiwano listy.")
        if kind == "object" and not isinstance(value, dict):
            errors.add(name, "Oczekiwano obiektu.")
    # unknown kinds pass through (provider-specific); the provider validates too


def _minutes(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def _validate_schedule(
    name: str, value: Any, constraints: dict[str, Any], errors: ValidationErrors
) -> None:
    if not isinstance(value, dict):
        errors.add(name, "Harmonogram musi być obiektem dni tygodnia.")
        return
    modes = constraints.get("modes")
    max_entries = constraints.get("maxEntries")
    overlap_allowed = constraints.get("overlapAllowed", True)
    resolution = constraints.get("resolution")
    for day, entries in value.items():
        if day not in DAYS:
            errors.add(name, f"Nieznany dzień: {day}.")
            continue
        if not isinstance(entries, list):
            errors.add(name, f"{day}: oczekiwano listy wpisów.")
            continue
        if max_entries is not None and len(entries) > max_entries:
            errors.add(name, f"{day}: maksymalnie {max_entries} wpisów.")
        spans: list[tuple[int, int]] = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.add(name, f"{day}[{i}]: oczekiwano obiektu.")
                continue
            start, end = str(entry.get("start", "")), str(entry.get("end", ""))
            if not TIME_RE.match(start) or not TIME_RE.match(end):
                errors.add(name, f"{day}[{i}]: format czasu HH:MM.")
                continue
            s, e = _minutes(start), _minutes(end)
            if s >= e:
                errors.add(name, f"{day}[{i}]: start musi być wcześniejszy niż koniec.")
            if resolution and (s % resolution or e % resolution):
                errors.add(name, f"{day}[{i}]: czas musi być wielokrotnością {resolution} min.")
            if modes is not None and entry.get("mode") not in modes:
                errors.add(name, f"{day}[{i}]: tryb spoza listy {modes}.")
            spans.append((s, e))
        if not overlap_allowed:
            spans.sort()
            for (_s1, e1), (s2, _e2) in zip(spans, spans[1:], strict=False):
                if s2 < e1:
                    errors.add(name, f"{day}: wpisy nakładają się.")
                    break


def numbers_match(expected: Any, actual: Any, stepping: float | None) -> bool:
    """Verification tolerance: stepping/2 for numbers (docs/07), exact otherwise."""
    if (
        isinstance(expected, int | float)
        and isinstance(actual, int | float)
        and not isinstance(expected, bool)
    ):
        tolerance = (stepping or 0) / 2 + EPS
        close: bool = math.isclose(float(expected), float(actual), abs_tol=tolerance)
        return close
    return bool(expected == actual)
