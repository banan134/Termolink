"""feature_name → group_key (docs/03 §Reguły grupowania). First match wins.

Patterns beyond the prefixes visible in real dumps are [ZAŁOŻENIE]; `feature_labels.group_key`
(stage 3) overrides this function.
"""

import re

_CIRCUIT = re.compile(r"^heating\.circuits\.(\d+)\.")


def group_key(feature_name: str) -> str:
    name = feature_name
    if name.startswith("device.messages") or name.endswith(".errors") or ".errors." in name:
        return "messages"
    if name.startswith("device."):
        return "device"
    m = _CIRCUIT.match(name)
    if m:
        return f"circuits.{m.group(1)}"
    if name.startswith("heating.dhw."):
        return "dhw"
    if (
        name.startswith(("heating.burners.", "heating.compressors.", "heating.boiler."))
        and ".sensors." not in name
    ):
        return "heat_source"
    if name.startswith("heating.solar."):
        return "solar"
    if name.startswith("ventilation."):
        return "ventilation"
    if name.startswith("heating.buffer."):
        return "buffer"
    if ".sensors." in name or name.startswith("heating.sensors."):
        return "sensors"
    if (
        name.startswith(("heating.power.", "heating.gas."))
        or name.endswith((".statistics", ".consumption"))
        or ".statistics." in name
        or ".consumption." in name
    ):
        return "statistics"
    return "other"


GROUP_ORDER = [
    "sensors",
    "circuits",  # circuits.N sorted by N
    "dhw",
    "heat_source",
    "solar",
    "ventilation",
    "buffer",
    "statistics",
    "messages",
    "device",
    "other",
]


def group_sort_key(key: str) -> tuple[int, int]:
    if key.startswith("circuits."):
        return (GROUP_ORDER.index("circuits"), int(key.split(".")[1]))
    return (GROUP_ORDER.index(key) if key in GROUP_ORDER else len(GROUP_ORDER), 0)
