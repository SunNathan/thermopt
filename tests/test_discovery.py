"""Tests for area-based entity discovery."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermopt.const import (
    CONF_ROOM_AREA,
    CONF_ROOM_ENERGY_ENTITY,
    CONF_ROOM_FIL_PILOTE_ENTITY,
    CONF_ROOM_HUMIDITY_ENTITY,
    CONF_ROOM_NAME,
    CONF_ROOM_POWER_ENTITY,
    CONF_ROOM_RELAY_ENTITY,
    CONF_ROOM_TEMP_ENTITY,
)
from custom_components.thermopt.discovery import guess_room_entities

SELECT_OPTIONS = [
    "comfort",
    "comfort_-1",
    "comfort_-2",
    "eco",
    "frost_protection",
    "off",
]


def _owner_entry(hass: HomeAssistant) -> str:
    """A real config entry, required to attach devices to the registry."""
    entry = MockConfigEntry(domain="mqtt", data={})
    entry.add_to_hass(hass)
    return entry.entry_id


def _build_area(hass: HomeAssistant) -> tuple[str, dict[str, str]]:
    """Area with a pilot wire module and a separate probe device."""
    salon = area_registry.async_get(hass).async_create("Salon")

    owner = _owner_entry(hass)
    devices = device_registry.async_get(hass)
    entities = entity_registry.async_get(hass)

    module = devices.async_get_or_create(
        config_entry_id=owner,
        identifiers={("mqtt", "module")},
        suggested_area="Salon",
        name="Radiateur Salon",
    )
    probe = devices.async_get_or_create(
        config_entry_id=owner,
        identifiers={("mqtt", "probe")},
        suggested_area="Salon",
        name="Sonde Salon",
    )

    created: dict[str, str] = {}
    for domain, object_id, device_id, device_class in (
        ("select", "salon_pilot_wire_mode", module.id, None),
        ("switch", "salon", module.id, None),
        ("sensor", "salon_power", module.id, "power"),
        ("sensor", "salon_energy", module.id, "energy"),
        ("sensor", "salon_temperature", probe.id, "temperature"),
        ("sensor", "salon_humidity", probe.id, "humidity"),
    ):
        entry = entities.async_get_or_create(
            domain,
            "mqtt",
            f"{object_id}_uid",
            suggested_object_id=object_id,
            device_id=device_id,
            original_device_class=device_class,
        )
        created[object_id] = entry.entity_id

    # Always use the ids the registry allocated: pre-setting the states would
    # make the registry pick suffixed object ids.
    hass.states.async_set(created["salon_pilot_wire_mode"], "comfort", {"options": SELECT_OPTIONS})
    hass.states.async_set(created["salon"], "on")

    return salon.id, created


async def test_guess_room_entities(hass: HomeAssistant) -> None:
    area_id, created = _build_area(hass)

    hints = await guess_room_entities(hass, area_id)

    assert hints[CONF_ROOM_AREA] == area_id
    assert hints[CONF_ROOM_NAME] == "Salon"
    assert hints[CONF_ROOM_FIL_PILOTE_ENTITY] == created["salon_pilot_wire_mode"]
    assert hints[CONF_ROOM_RELAY_ENTITY] == created["salon"]
    assert hints[CONF_ROOM_POWER_ENTITY] == created["salon_power"]
    assert hints[CONF_ROOM_ENERGY_ENTITY] == created["salon_energy"]
    # Sensors live on another device: they must still be found through the area.
    assert hints[CONF_ROOM_TEMP_ENTITY] == created["salon_temperature"]
    assert hints[CONF_ROOM_HUMIDITY_ENTITY] == created["salon_humidity"]


async def test_guess_room_entities_unknown_area(hass: HomeAssistant) -> None:
    assert await guess_room_entities(hass, "does_not_exist") == {}


async def test_guess_room_entities_without_pilot_wire(hass: HomeAssistant) -> None:
    bureau = area_registry.async_get(hass).async_create("Bureau")

    hints = await guess_room_entities(hass, bureau.id)
    assert hints[CONF_ROOM_NAME] == "Bureau"
    assert CONF_ROOM_FIL_PILOTE_ENTITY not in hints


async def test_discovery_ignores_select_without_frost_option(hass: HomeAssistant) -> None:
    salon = area_registry.async_get(hass).async_create("Salon")
    devices = device_registry.async_get(hass)
    entities = entity_registry.async_get(hass)

    device = devices.async_get_or_create(
        config_entry_id=_owner_entry(hass),
        identifiers={("mqtt", "other")},
    )
    entry = entities.async_get_or_create(
        "select",
        "mqtt",
        "autre_uid",
        suggested_object_id="autre",
        device_id=device.id,
    )
    hass.states.async_set(entry.entity_id, "a", {"options": ["a", "b"]})

    hints = await guess_room_entities(hass, salon.id)
    assert CONF_ROOM_FIL_PILOTE_ENTITY not in hints
