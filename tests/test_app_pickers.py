"""Tests for the configuration form pickers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.pickers import (
    NOT_FOUND,
    OUT_OF_FILTER,
    pick_by_domain,
    pick_fil_pilote,
    pick_options,
)


@dataclass
class FakeState:
    entity_id: str
    state: str = "on"
    attributes: dict = field(default_factory=dict)


def _states() -> dict[str, FakeState]:
    return {
        "sensor.salon_temperature": FakeState(
            "sensor.salon_temperature",
            "21.0",
            {"friendly_name": "Salon Température", "device_class": "temperature"},
        ),
        "sensor.chambre_temperature": FakeState(
            "sensor.chambre_temperature",
            "19.0",
            {"friendly_name": "Chambre Température", "device_class": "temperature"},
        ),
        "sensor.salon_humidity": FakeState(
            "sensor.salon_humidity",
            "45",
            {"friendly_name": "Salon Humidité", "device_class": "humidity"},
        ),
        "sensor.salon_power": FakeState(
            "sensor.salon_power",
            "800",
            {"friendly_name": "Salon Puissance", "device_class": "power"},
        ),
        "sensor.template_room": FakeState(
            "sensor.template_room", "20.5", {"friendly_name": "Capteur bricolé"}
        ),
        "select.salon_pilot_wire_mode": FakeState(
            "select.salon_pilot_wire_mode",
            "comfort",
            {
                "friendly_name": "Salon Pilote",
                "options": [
                    "comfort",
                    "comfort_-1",
                    "comfort_-2",
                    "eco",
                    "frost_protection",
                    "off",
                ],
            },
        ),
        "select.mode_maison": FakeState(
            "select.mode_maison",
            "nuit",
            {"friendly_name": "Mode maison", "options": ["jour", "nuit"]},
        ),
        "switch.salon": FakeState("switch.salon", "on", {"friendly_name": "Salon"}),
        "weather.home": FakeState("weather.home", "sunny", {"friendly_name": "Météo"}),
        "input_boolean.thermopt_repli": FakeState(
            "input_boolean.thermopt_repli", "off", {"friendly_name": "ThermOpt repli"}
        ),
    }


def test_filter_by_device_class() -> None:
    options = pick_options(_states(), domain="sensor", device_class="temperature")
    values = [value for value, _label in options]

    assert values == ["sensor.chambre_temperature", "sensor.salon_temperature"]
    assert all("temperature" in label for _value, label in options if "(" in label)


def test_labels_use_the_friendly_name() -> None:
    options = dict(pick_options(_states(), domain="sensor", device_class="power"))
    assert options["sensor.salon_power"] == "Salon Puissance (sensor.salon_power)"


def test_current_value_outside_the_filter_is_kept() -> None:
    options = pick_options(
        _states(),
        domain="sensor",
        device_class="temperature",
        current="sensor.template_room",
    )
    values = [value for value, _label in options]

    assert values[0] == "sensor.template_room"
    assert OUT_OF_FILTER in options[0][1]


def test_missing_current_value_is_marked() -> None:
    options = pick_options(
        _states(), domain="sensor", device_class="temperature", current="sensor.gone"
    )
    assert options[0] == ("sensor.gone", "sensor.gone (introuvable)")
    assert NOT_FOUND in options[0][1]


def test_current_value_inside_the_filter_is_not_duplicated() -> None:
    options = pick_options(
        _states(),
        domain="sensor",
        device_class="temperature",
        current="sensor.salon_temperature",
    )
    values = [value for value, _label in options]
    assert values.count("sensor.salon_temperature") == 1


def test_empty_filter_falls_back_to_the_domain() -> None:
    """A template sensor without a device class must still be selectable."""
    options = pick_options(_states(), domain="sensor", device_class="battery")
    values = [value for value, _label in options]
    assert "sensor.template_room" in values
    assert "sensor.salon_temperature" in values


def test_fil_pilote_only_keeps_pilot_wire_modules() -> None:
    options = pick_fil_pilote(_states())
    values = [value for value, _label in options]
    assert values == ["select.salon_pilot_wire_mode"]


def test_fil_pilote_falls_back_to_all_selects() -> None:
    states = {
        "select.mode_maison": FakeState("select.mode_maison", "nuit", {"options": ["jour", "nuit"]})
    }
    values = [value for value, _label in pick_fil_pilote(states)]
    assert values == ["select.mode_maison"]


def test_by_domain() -> None:
    assert [v for v, _l in pick_by_domain(_states(), "weather")] == ["weather.home"]
    assert [v for v, _l in pick_by_domain(_states(), "input_boolean")] == [
        "input_boolean.thermopt_repli"
    ]


def test_options_are_sorted_by_label() -> None:
    labels = [label for _value, label in pick_options(_states(), domain="sensor")]
    assert labels == sorted(labels, key=str.lower)
