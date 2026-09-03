"""docs/05 §Walidacja — every rule with an OK and an error case (docs/12)."""

from apps.control.validation import numbers_match, validate_params

NUM = {
    "params": {
        "targetTemperature": {
            "type": "number",
            "required": True,
            "constraints": {"min": 3, "max": 37, "stepping": 1},
        }
    }
}
DEC = {
    "params": {
        "slope": {
            "type": "number",
            "required": True,
            "constraints": {"min": 0.2, "max": 3.5, "stepping": 0.1},
        }
    }
}
ENUM = {
    "params": {
        "mode": {
            "type": "string",
            "required": True,
            "constraints": {"enum": ["standby", "heating"]},
        }
    }
}
NAME = {"params": {"name": {"type": "string", "required": True, "constraints": {"maxLength": 20}}}}
BOOL = {"params": {"active": {"type": "boolean", "required": True}}}
SCHED = {
    "params": {
        "newSchedule": {
            "type": "Schedule",
            "required": True,
            "constraints": {
                "maxEntries": 4,
                "modes": ["normal", "reduced", "comfort"],
                "resolution": 10,
                "overlapAllowed": False,
            },
        }
    }
}


def test_number_min_max_stepping() -> None:
    assert not validate_params(NUM, {"targetTemperature": 21})
    assert "targetTemperature" in validate_params(NUM, {"targetTemperature": 2})
    assert "targetTemperature" in validate_params(NUM, {"targetTemperature": 38})
    assert "targetTemperature" in validate_params(NUM, {"targetTemperature": 21.5})
    assert "targetTemperature" in validate_params(NUM, {"targetTemperature": "21"})
    assert "targetTemperature" in validate_params(NUM, {"targetTemperature": True})


def test_decimal_stepping_uses_tolerance() -> None:
    assert not validate_params(DEC, {"slope": 1.2})  # (1.2-0.2)/0.1 = 10 within 1e-9
    assert not validate_params(DEC, {"slope": 0.5})
    assert "slope" in validate_params(DEC, {"slope": 0.55})


def test_string_enum_and_max_length() -> None:
    assert not validate_params(ENUM, {"mode": "heating"})
    assert "mode" in validate_params(ENUM, {"mode": "party"})
    assert not validate_params(NAME, {"name": "Parter"})
    assert "name" in validate_params(NAME, {"name": "x" * 21})
    assert "name" in validate_params(NAME, {"name": 5})


def test_boolean_required_and_unknown_params() -> None:
    assert not validate_params(BOOL, {"active": True})
    assert "active" in validate_params(BOOL, {"active": "yes"})
    assert "active" in validate_params(BOOL, {})  # required missing
    assert "extra" in validate_params(BOOL, {"active": True, "extra": 1})


def test_schedule_rules() -> None:
    ok = {
        "mon": [
            {"start": "06:00", "end": "08:00", "mode": "comfort"},
            {"start": "08:00", "end": "22:00", "mode": "normal"},
        ]
    }
    assert not validate_params(SCHED, {"newSchedule": ok})
    bad_day: dict[str, list[dict[str, str]]] = {"xyz": []}
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": bad_day})
    bad_time = {"mon": [{"start": "6:00", "end": "08:00", "mode": "comfort"}]}
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": bad_time})
    reversed_ = {"mon": [{"start": "09:00", "end": "08:00", "mode": "comfort"}]}
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": reversed_})
    bad_mode = {"mon": [{"start": "06:00", "end": "08:00", "mode": "party"}]}
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": bad_mode})
    too_many = {
        "mon": [{"start": f"0{i}:00", "end": f"0{i + 1}:00", "mode": "normal"} for i in range(5)]
    }
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": too_many})
    overlap = {
        "mon": [
            {"start": "06:00", "end": "09:00", "mode": "comfort"},
            {"start": "08:00", "end": "10:00", "mode": "normal"},
        ]
    }
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": overlap})
    off_grid = {"mon": [{"start": "06:05", "end": "08:00", "mode": "comfort"}]}
    assert "newSchedule" in validate_params(SCHED, {"newSchedule": off_grid})


def test_numbers_match_tolerance() -> None:
    assert numbers_match(21, 21.4, 1)  # within stepping/2
    assert not numbers_match(21, 21.6, 1)
    assert numbers_match(21, 21, None)
    assert numbers_match("heating", "heating", None)
    assert not numbers_match("heating", "standby", None)
