"""State visibility: can the user tell whether ThermOpt controls the heating?"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_init import ROOM, SYSTEM, _room_entry, _set_states, _setup

from custom_components.thermopt.const import (
    CONF_COMFORT_SETPOINT,
    CONF_ROOM_AREA,
    DOMAIN,
    SUPERVISOR_MODES,
)
from custom_components.thermopt.dashboard import (
    build_dashboard_yaml,
    collect,
    validate_dashboard_yaml,
)

STRINGS = Path(__file__).resolve().parents[1] / "custom_components" / "thermopt" / "strings.json"


def _by_key(hass: HomeAssistant, platform: str, needle: str):
    return [
        state
        for state in hass.states.async_all(platform)
        if needle in state.entity_id and state.entity_id.startswith(f"{platform}.")
    ]


@pytest.fixture
def weather_service(hass):
    """Minimal forecast so that the weather flag does not degrade the state."""
    from homeassistant.core import ServiceCall, SupportsResponse

    async def _get_forecasts(call: ServiceCall) -> dict:
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        from datetime import timedelta

        return {
            call.data["entity_id"]: {
                "forecast": [
                    {
                        "datetime": (now + timedelta(hours=hour)).isoformat(),
                        "temperature": 6.0 - hour * 0.2,
                    }
                    for hour in range(24)
                ]
            }
        }

    hass.services.async_register(
        "weather",
        "get_forecasts",
        _get_forecasts,
        supports_response=SupportsResponse.ONLY,
    )


async def test_pilotage_is_explicitly_inactive(hass: HomeAssistant, weather_service) -> None:
    """The whole point: the binary sensor says no order is sent, and why."""
    _set_states(hass)
    await _setup(hass, _room_entry())

    pilotage = _by_key(hass, "binary_sensor", "pilotage_actif")
    assert pilotage, [s.entity_id for s in hass.states.async_all("binary_sensor")]
    assert pilotage[0].state == "off"
    assert "non implémenté" in pilotage[0].attributes["raison"]
    assert pilotage[0].attributes["mode"] == "observation"


async def test_status_is_observation_and_last_command_empty(
    hass: HomeAssistant, weather_service
) -> None:
    _set_states(hass)
    await _setup(hass, _room_entry())

    status = _by_key(hass, "sensor", "statut")
    assert status[0].state == "observation"
    assert status[0].attributes["pilotage_actif"] is False
    assert status[0].attributes["etat_interne"]

    command = _by_key(hass, "sensor", "derniere_commande")
    assert command, [s.entity_id for s in hass.states.async_all("sensor")]
    assert command[0].state in ("unknown", "unavailable")
    assert command[0].attributes["resultat"] == "aucune"


async def test_order_sensors_distinguish_requested_and_applied(
    hass: HomeAssistant, weather_service
) -> None:
    _set_states(hass)
    await _setup(hass, _room_entry())

    applied = _by_key(hass, "sensor", "ordre_applique")
    requested = _by_key(hass, "sensor", "ordre_demande")
    assert applied and requested
    assert applied[0].state == "comfort"  # mirror of the module
    assert applied[0].attributes["source"] in ("manuel", "inconnue")
    assert requested[0].state in ("unknown", "unavailable")  # nothing requested yet


async def test_room_device_lands_in_the_chosen_area(hass: HomeAssistant, weather_service) -> None:
    _set_states(hass)
    salon = area_registry.async_get(hass).async_create("Salon")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ThermOpt",
        data=SYSTEM,
        subentries_data=(
            {
                "subentry_id": "room_salon",
                "subentry_type": "room",
                "title": "Salon",
                "data": {**ROOM, CONF_ROOM_AREA: salon.id},
                "unique_id": None,
            },
        ),
    )
    await _setup(hass, entry)

    registry = device_registry.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_room_salon")})
    assert device is not None
    assert device.area_id == salon.id

    # The hub device keeps its own area, it must not be moved by the room.
    hub = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert hub is not None
    assert hub.area_id is None


def test_every_mode_is_translated() -> None:
    """An enum sensor without a translated state shows a raw slug in the UI."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    states = strings["entity"]["sensor"]["status"]["state"]
    missing = [mode for mode in SUPERVISOR_MODES if mode not in states]
    assert not missing, f"Missing translations for modes: {missing}"


async def test_pieces_sensor_lists_every_room(hass: HomeAssistant, weather_service) -> None:
    _set_states(hass)
    await _setup(hass, _room_entry())

    pieces = _by_key(hass, "sensor", "pieces")
    assert pieces, [s.entity_id for s in hass.states.async_all("sensor")]
    assert pieces[0].state == "1"

    rooms = pieces[0].attributes["rooms"]
    assert rooms[0]["name"] == "Salon"
    assert rooms[0]["t_air"] == 18.4
    assert rooms[0]["applied"] == "comfort"
    assert "source" in rooms[0]


async def test_degraded_detail_is_a_readable_sentence(hass: HomeAssistant, weather_service) -> None:
    """C = 20 °C must produce an explanation, not a raw key."""
    _set_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ThermOpt",
        data={**SYSTEM, CONF_COMFORT_SETPOINT: 20.0},
        subentries_data=(
            {
                "subentry_id": "room_salon",
                "subentry_type": "room",
                "title": "Salon",
                "data": ROOM,
                "unique_id": None,
            },
        ),
    )
    await _setup(hass, entry)

    degraded = _by_key(hass, "binary_sensor", "mode_degrade")[0]
    assert degraded.state == "on"
    assert "profile_unreachable" in degraded.attributes["reasons"]

    details = degraded.attributes["details"]
    assert details, degraded.attributes
    assert any("20,5" in line for line in details), details
    # The status sensor carries the same explanation, for the dashboard.
    assert _by_key(hass, "sensor", "statut")[0].attributes["degraded_detail"]


async def test_dashboard_generator_uses_real_entity_ids(
    hass: HomeAssistant, weather_service
) -> None:
    _set_states(hass)
    entry = await _setup_and_return(hass)

    runtime = entry.runtime_data
    data = collect(hass, runtime)

    assert "pilotage_actif" in data.system
    assert "status" in data.system
    assert data.rooms["Salon"]["temperature"] == "sensor.salon_temperature_mesuree"
    assert data.rooms["Salon"]["applied_order"] == "sensor.salon_ordre_applique"
    assert "systeme: status" not in data.missing

    yaml_text = build_dashboard_yaml(data)
    assert validate_dashboard_yaml(yaml_text) is None

    parsed = yaml.safe_load(yaml_text)
    assert isinstance(parsed, dict)
    assert "views" in parsed

    view = parsed["views"][0]
    assert view["path"] == "thermopt"
    assert [card["type"] for card in view["cards"]] == [
        "markdown",
        "glance",
        "entities",
        "conditional",
    ]
    # The paste target is the whole dashboard, and markdown keeps its newlines.
    assert "\n" in view["cards"][0]["content"]
    assert "sensor.salon_temperature_mesuree" in yaml_text


async def _setup_and_return(hass: HomeAssistant) -> MockConfigEntry:
    entry = _room_entry()
    await _setup(hass, entry)
    return entry
