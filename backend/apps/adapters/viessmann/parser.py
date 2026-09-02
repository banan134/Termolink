"""Raw Viessmann JSON → normalised model (docs/01 §4 rules, docs/05).

Rules:
1. Never assume any specific feature exists; keep everything the API sends.
2. isEnabled == false → definition with enabled=False (no history — decided by ingest).
3. A command is executable only when isExecutable == true.
4. Types number/string/boolean/array pass through; "Schedule" → "schedule"; other → "object".
5. The feature `timestamp` is the device time (ts_device), not the poll time.

Fixture-based tests (backend/tests/fixtures/viessmann/*.json, stage 0) are the source of truth;
the docstring example in docs/01 §4 is the only structure verified so far.
"""

from typing import Any

from ..base import CommandDef, DeviceDescriptor, Feature, ParamDef, PropertyDef, ValueType

_TYPE_MAP: dict[str, ValueType] = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    "schedule": "schedule",
}


def normalise_type(raw: Any) -> ValueType:
    key = str(raw or "").strip().lower()
    return _TYPE_MAP.get(key, "object")


def parse_feature(raw: dict[str, Any]) -> Feature:
    properties: dict[str, PropertyDef] = {}
    for name, prop in (raw.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        unit = prop.get("unit")
        properties[name] = PropertyDef(
            name=name,
            type=normalise_type(prop.get("type")),
            unit=str(unit) if unit not in (None, "") else None,
            value=prop.get("value"),
            ts_device=raw.get("timestamp"),
        )
    commands: dict[str, CommandDef] = {}
    for name, cmd in (raw.get("commands") or {}).items():
        if not isinstance(cmd, dict):
            continue
        params: dict[str, ParamDef] = {}
        for pname, pdef in (cmd.get("params") or {}).items():
            if not isinstance(pdef, dict):
                continue
            params[pname] = ParamDef(
                name=pname,
                type=normalise_type(pdef.get("type")),
                required=bool(pdef.get("required", False)),
                constraints=dict(pdef.get("constraints") or {}),
            )
        commands[name] = CommandDef(
            name=name,
            executable=cmd.get("isExecutable") is True,
            params=params,
            uri=str(cmd["uri"]) if cmd.get("uri") else None,
        )
    return Feature(
        name=str(raw.get("feature") or raw.get("name") or ""),
        enabled=raw.get("isEnabled") is not False,
        ready=raw.get("isReady") is not False,
        properties=properties,
        commands=commands,
        raw=raw,
    )


def parse_features(payload: Any) -> list[Feature]:
    """Accepts {"data": [...]} (API shape) or a bare list."""
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    features = [parse_feature(item) for item in (items or []) if isinstance(item, dict)]
    return [f for f in features if f.name]


def parse_installations(payload: Any) -> list[DeviceDescriptor]:
    """GET /equipment/installations?includeGateways=true → one descriptor per device."""
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    devices: list[DeviceDescriptor] = []
    for inst in items or []:
        if not isinstance(inst, dict):
            continue
        for gw in inst.get("gateways") or []:
            if not isinstance(gw, dict):
                continue
            for dev in gw.get("devices") or []:
                if not isinstance(dev, dict):
                    continue
                device_id = str(dev.get("id", ""))
                devices.append(
                    DeviceDescriptor(
                        external_ids={
                            "installationId": str(inst.get("id", "")),
                            "gatewaySerial": str(gw.get("serial", "")),
                            "deviceId": device_id,
                        },
                        model=dev.get("modelId"),
                        serial=dev.get("serial") or None,
                        device_type=(
                            "gateway" if device_id == "gateway" else dev.get("deviceType")
                        ),
                        online=(str(dev.get("status", "")).lower() == "online")
                        if dev.get("status") is not None
                        else None,
                        raw=dev,
                    )
                )
    return devices
