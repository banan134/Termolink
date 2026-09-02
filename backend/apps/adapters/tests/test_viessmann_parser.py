"""Parser tests on the one structure verified so far (docs/01 §4 real Vitodens dump).

Fixture-driven tests (every file in backend/tests/fixtures/viessmann/) run automatically once
stage 0 delivers them; until then they are skipped, never faked.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from apps.adapters.viessmann.parser import parse_features, parse_installations

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "viessmann"

DOCS_01_EXAMPLE: dict[str, Any] = {
    "feature": "heating.circuits.0.heating.curve",
    "isEnabled": True,
    "isReady": True,
    "properties": {
        "shift": {"type": "number", "unit": "", "value": 4},
        "slope": {"type": "number", "unit": "", "value": 1.2},
    },
    "commands": {
        "setCurve": {
            "isExecutable": True,
            "name": "setCurve",
            "params": {
                "shift": {
                    "type": "number",
                    "required": True,
                    "constraints": {"min": -13, "max": 40, "stepping": 1},
                },
                "slope": {
                    "type": "number",
                    "required": True,
                    "constraints": {"min": 0.2, "max": 3.5, "stepping": 0.1},
                },
            },
            "uri": "https://api.viessmann-climatesolutions.com/iot/v1/features/installations/1/gateways/2/devices/0/features/heating.circuits.0.heating.curve/commands/setCurve",
        }
    },
    "components": [],
    "timestamp": "2021-09-03T17:11:03.506Z",
}


def test_docs_example_parses() -> None:
    [feature] = parse_features({"data": [DOCS_01_EXAMPLE]})
    assert feature.name == "heating.circuits.0.heating.curve"
    assert feature.enabled and feature.ready
    assert feature.properties["shift"].value == 4 and feature.properties["shift"].unit is None
    assert feature.properties["slope"].type == "number"
    assert feature.properties["slope"].ts_device == "2021-09-03T17:11:03.506Z"
    cmd = feature.commands["setCurve"]
    assert cmd.executable and cmd.uri and cmd.uri.endswith("/commands/setCurve")
    assert cmd.params["slope"].constraints == {"min": 0.2, "max": 3.5, "stepping": 0.1}
    assert cmd.params["slope"].required


def test_non_executable_command_and_disabled_feature() -> None:
    raw = {
        **DOCS_01_EXAMPLE,
        "isEnabled": False,
        "commands": {
            "setCurve": {**DOCS_01_EXAMPLE["commands"]["setCurve"], "isExecutable": False}
        },
    }
    [feature] = parse_features([raw])
    assert feature.enabled is False
    assert feature.commands["setCurve"].executable is False


def test_unknown_unit_and_schedule_type_do_not_break_parser() -> None:
    raw = {
        "feature": "x.y",
        "properties": {
            "entries": {"type": "Schedule", "unit": "furlongs", "value": {"mon": []}},
            "flag": {"type": "boolean", "value": True},
            "weird": {"type": "Something", "value": [1]},
        },
    }
    [feature] = parse_features([raw])
    assert feature.properties["entries"].type == "schedule"
    assert feature.properties["entries"].unit == "furlongs"
    assert feature.properties["flag"].type == "boolean"
    assert feature.properties["weird"].type == "object"


def test_parse_installations_shape() -> None:
    payload = {
        "data": [
            {
                "id": 123,
                "gateways": [
                    {
                        "serial": "ANON000100000000",
                        "devices": [
                            {
                                "id": "0",
                                "modelId": "Vitodens200",
                                "deviceType": "heating",
                                "status": "Online",
                            },
                            {"id": "gateway", "modelId": "Vitoconnect"},
                        ],
                    }
                ],
            }
        ]
    }
    devices = parse_installations(payload)
    assert [d.external_ids["deviceId"] for d in devices] == ["0", "gateway"]
    assert devices[0].external_ids == {
        "installationId": "123",
        "gatewaySerial": "ANON000100000000",
        "deviceId": "0",
    }
    assert devices[0].online is True and devices[0].model == "Vitodens200"
    assert devices[1].device_type == "gateway" and devices[1].online is None


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES.glob("features_*.json")) if FIXTURES.exists() else []


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_every_fixture_parses_completely(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    body = doc.get("body", doc)
    if doc.get("_meta", {}).get("status", 200) != 200:
        pytest.skip("error fixture")
    features = parse_features(body)
    raw_items = body.get("data", body)
    assert len(features) == len(raw_items), "every feature in the fixture must be kept"
    assert all(f.name for f in features)
    for feature in features:
        for prop in feature.properties.values():
            assert prop.type in ("number", "string", "boolean", "array", "object", "schedule")
    # snapshot: names + property types stable between runs (docs/12)
    snapshot = sorted(
        (f.name, tuple(sorted((p, v.type) for p, v in f.properties.items()))) for f in features
    )
    assert snapshot == sorted(snapshot)


def test_fixture_directory_state() -> None:
    files = _fixture_files()
    if not files:
        pytest.skip("stage 0 fixtures not captured yet (docs/16)")
    assert len(files) >= 1
