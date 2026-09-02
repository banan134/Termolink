import pytest

from apps.devices.grouping import group_key, group_sort_key


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("device.messages.errors.raw", "messages"),
        ("heating.circuits.0.errors", "messages"),
        ("device.serial", "device"),
        ("heating.circuits.0.sensors.temperature.supply", "circuits.0"),
        ("heating.circuits.12.operating.modes.active", "circuits.12"),
        ("heating.dhw.temperature.main", "dhw"),
        ("heating.burners.0.statistics", "heat_source"),
        ("heating.compressors.0", "heat_source"),
        ("heating.boiler.temperature", "heat_source"),
        ("heating.boiler.sensors.temperature.commonSupply", "sensors"),
        ("heating.solar.power.production", "solar"),
        ("ventilation.operating.modes.active", "ventilation"),
        ("heating.buffer.sensors.temperature.main", "buffer"),
        ("heating.sensors.temperature.outside", "sensors"),
        ("heating.power.consumption.total", "statistics"),
        ("heating.gas.consumption.heating", "statistics"),
        ("something.completely.new", "other"),
    ],
)
def test_group_key(name: str, expected: str) -> None:
    assert group_key(name) == expected


def test_group_order_puts_sensors_first_circuits_numerically_and_other_last() -> None:
    keys = ["other", "circuits.10", "dhw", "sensors", "circuits.2", "messages", "zzz"]
    assert sorted(keys, key=group_sort_key) == [
        "sensors",
        "circuits.2",
        "circuits.10",
        "dhw",
        "messages",
        "other",
        "zzz",
    ]
