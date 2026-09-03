"""VIESSMANN_MOCK=1: adapter that serves stage-0 fixtures instead of the real API (docs/15).

Reads backend/tests/fixtures/viessmann/installations.json and features_<model>_<deviceId>.json,
jitters numeric values slightly so charts move, and never touches the network or the budget
of a real account. With no fixtures captured yet it returns an empty installation list.
"""

import json
import random
from pathlib import Path
from typing import Any

from ..base import (
    AuthKind,
    AuthStart,
    Budget,
    CommandResult,
    DeviceDescriptor,
    Feature,
    ProviderTokens,
)
from .parser import parse_features, parse_installations

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "viessmann"


def _load(name: str) -> Any:
    path = FIXTURES / name
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("body", doc)


class MockViessmannAdapter:
    id: str = "viessmann"
    display_name: str = "Viessmann (MOCK — fixtures)"
    auth_kind: AuthKind = "oauth2_pkce"
    default_budget: Budget = Budget(limit=1450, window_s=86400, short_limit=120, short_window_s=600)

    def auth_start(self, redirect_uri: str, state: str) -> AuthStart:
        return AuthStart(
            url=f"{redirect_uri}?code=mock&state={state}", saved={"code_verifier": "mock"}
        )

    async def auth_finish(
        self, redirect_uri: str, callback: dict[str, Any], saved: dict[str, Any]
    ) -> ProviderTokens:
        return ProviderTokens(
            access_token="mock",  # noqa: S106
            access_expires_at=4102444800.0,
            refresh_token="mock-refresh",  # noqa: S106
            external_user_id="mock-user",
        )

    async def refresh(self, tokens: ProviderTokens) -> ProviderTokens:
        return ProviderTokens(
            access_token="mock",  # noqa: S106
            access_expires_at=4102444800.0,
            refresh_token=tokens.refresh_token,
        )

    async def discover(self, tokens: ProviderTokens) -> list[DeviceDescriptor]:
        payload = _load("installations.json")
        return parse_installations(payload) if payload else []

    async def read_features(
        self, tokens: ProviderTokens, device: DeviceDescriptor
    ) -> list[Feature]:
        device_id = device.external_ids.get("deviceId", "0")
        candidates = (
            sorted(FIXTURES.glob(f"features_*_{device_id}.json")) if FIXTURES.exists() else []
        )
        if device.model:
            preferred = [p for p in candidates if device.model in p.name]
            candidates = preferred or candidates
        if not candidates:
            return []
        payload = _load(candidates[0].name)
        features = parse_features(payload)
        return [_apply_overrides(_jitter(f)) for f in features]

    async def execute(
        self,
        tokens: ProviderTokens,
        device: DeviceDescriptor,
        feature: Feature,
        command: str,
        params: dict[str, Any],
    ) -> CommandResult:
        # remember the change so the verify read (same worker process) sees the new value
        for param, value in params.items():
            prop = _property_for(feature, param)
            if prop is not None:
                _OVERRIDES.setdefault(feature.name, {})[prop] = value
        return CommandResult(ok=True, http_status=200, response={"mock": True, "params": params})

    def calls_per_read(self) -> int:
        return 1


_OVERRIDES: dict[str, dict[str, Any]] = {}
_PARAM_ALIASES = {
    "targetTemperature": ("temperature", "value"),
    "temperature": ("temperature", "value"),
    "mode": ("value",),
    "name": ("name", "value"),
    "newSchedule": ("entries",),
}


def _property_for(feature: Feature, param: str) -> str | None:
    if param in feature.properties:
        return param
    for candidate in _PARAM_ALIASES.get(param, ()):
        if candidate in feature.properties:
            return candidate
    if len(feature.properties) == 1:
        return next(iter(feature.properties))
    if not feature.properties:  # control passes a definition-only Feature (no live properties)
        aliases = _PARAM_ALIASES.get(param)
        return aliases[0] if aliases else param
    return None


def _apply_overrides(feature: Feature) -> Feature:
    from dataclasses import replace

    overrides = _OVERRIDES.get(feature.name)
    if not overrides:
        return feature
    props = {
        name: (replace(prop, value=overrides[name]) if name in overrides else prop)
        for name, prop in feature.properties.items()
    }
    return replace(feature, properties=props)


def _jitter(feature: Feature) -> Feature:
    """±1 % on numeric sensor-like values so dev charts are not flat lines."""
    from dataclasses import replace

    props = {}
    for name, prop in feature.properties.items():
        value = prop.value
        if (
            prop.type == "number"
            and isinstance(value, int | float)
            and not isinstance(value, bool)
            and prop.unit
        ):
            value = round(float(value) * (1 + random.uniform(-0.01, 0.01)), 2)  # noqa: S311 — cosmetic
        props[name] = replace(prop, value=value)
    return replace(feature, properties=props)
