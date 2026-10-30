"""Integration tests: the safety layer actually writes, and only when allowed."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_init import ROOM, SELECT_OPTIONS, SYSTEM, _set_states, _setup

from custom_components.thermopt.const import (
    CONF_AUTO_ENTITY,
    CONF_FALLBACK_ENTITY,
    DOMAIN,
)
from custom_components.thermopt.core.orders import Order

NIGHT = "2026-01-05 03:00:00"  # Monday 03:00, night slot (T_min = 17 °C)


@pytest.fixture
def select_calls(hass: HomeAssistant) -> list[dict]:
    """Capture select.select_option, which does not exist in the test harness."""
    calls: list[dict] = []

    async def _select_option(call) -> None:
        calls.append(dict(call.data))
        hass.states.async_set(
            call.data["entity_id"], call.data["option"], {"options": SELECT_OPTIONS}
        )

    hass.services.async_register("select", "select_option", _select_option)
    return calls


def _entities(hass: HomeAssistant, platform: str, needle: str):
    return [
        state
        for state in hass.states.async_all(platform)
        if state.entity_id.startswith(f"{platform}.") and needle in state.entity_id
    ]


def _entry(extra: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="ThermOpt",
        data={**SYSTEM, **(extra or {})},
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


async def test_cold_room_forces_comfort(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="16.0")
    # Start on Eco so the guard has an actual change to make.
    hass.states.async_set("select.salon_pilot_wire_mode", "eco", {"options": SELECT_OPTIONS})
    await _setup(hass, _entry())

    assert select_calls, "the safety layer must have written an order"
    assert select_calls[-1]["option"] == "comfort"

    applied = _entities(hass, "sensor", "ordre_applique")[0]
    assert applied.state == "comfort"

    safety = _entities(hass, "sensor", "salon_securite")[0]
    assert safety.state == "plancher"
    assert "borne de confort" in safety.attributes["raison"]

    command = _entities(hass, "sensor", "derniere_commande")[0]
    assert command.attributes["resultat"] == "envoyee"
    assert command.attributes["source"] == "securite"
    assert command.attributes["ordre"] == "comfort"


async def test_warm_room_writes_nothing(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="21.0")
    await _setup(hass, _entry())

    assert select_calls == []


async def test_manual_mode_blocks_writes(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="16.0")
    hass.states.async_set("input_boolean.thermopt_auto", "off")

    await _setup(hass, _entry({CONF_AUTO_ENTITY: "input_boolean.thermopt_auto"}))

    assert select_calls == []
    assert _entities(hass, "sensor", "statut")[0].state == "manuel"


async def test_fallback_blocks_writes(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="16.0")
    hass.states.async_set("input_boolean.thermopt_repli", "on")

    await _setup(hass, _entry({CONF_FALLBACK_ENTITY: "input_boolean.thermopt_repli"}))

    assert select_calls == []
    assert _entities(hass, "sensor", "statut")[0].state == "repli"


async def test_relay_off_still_gets_restored(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="16.0", relay="off")
    await _setup(hass, _entry())

    degraded = _entities(hass, "binary_sensor", "mode_degrade")[0]
    assert "relay_off" in degraded.attributes["reasons"]


async def test_missing_effect_is_detected(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="16.0")  # power stays at 780 W by default
    hass.states.async_set("sensor.salon_power", "0")
    hass.states.async_set("select.salon_pilot_wire_mode", "eco", {"options": SELECT_OPTIONS})
    entry = _entry()
    await _setup(hass, entry)

    room = entry.runtime_data.rooms["room_salon"]
    assert room.pending_check is not None

    freezer.tick(timedelta(minutes=16))
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    degraded = _entities(hass, "binary_sensor", "mode_degrade")[0]
    assert "no_effect" in degraded.attributes["reasons"]
    assert any("puissance" in line for line in degraded.attributes["details"])


async def test_manual_override_holds_for_two_hours(
    hass: HomeAssistant, weather_service, select_calls, freezer
) -> None:
    freezer.move_to(NIGHT)
    _set_states(hass, temperature="21.0")
    entry = _entry()
    await _setup(hass, entry)

    room = entry.runtime_data.rooms["room_salon"]
    room.last_written = Order.COMFORT
    room.last_write_at = None  # no grace window in this test
    hass.states.async_set("select.salon_pilot_wire_mode", "eco", {"options": SELECT_OPTIONS})

    from homeassistant.util import dt as dt_util

    now = dt_util.now()
    assert room.update_manual_override(now) is True
    assert room.manual_hold_until is not None
    assert (room.manual_hold_until - now) == timedelta(minutes=120)
