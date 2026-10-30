"""Room subentry flow: menu, discovery path, manual creation."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_init import ROOM, SYSTEM

from custom_components.thermopt.const import (
    CONF_ROOM_AREA,
    CONF_ROOM_FIL_PILOTE_ENTITY,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_ENTITY,
    DOMAIN,
    SUBENTRY_ROOM,
)


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=SYSTEM)
    entry.add_to_hass(hass)
    return entry


async def _init_flow(hass: HomeAssistant, entry: MockConfigEntry):
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM),
        context={"source": config_entries.SOURCE_USER},
    )


async def test_room_flow_shows_a_menu(hass: HomeAssistant) -> None:
    entry = _entry(hass)

    result = await _init_flow(hass, entry)

    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"manual", "from_area"}


async def test_manual_room_creation(hass: HomeAssistant) -> None:
    entry = _entry(hass)

    result = await _init_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"

    result = await hass.config_entries.subentries.async_configure(result["flow_id"], ROOM)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salon"


async def test_manual_room_requires_an_actuator(hass: HomeAssistant) -> None:
    entry = _entry(hass)

    result = await _init_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    payload = {k: v for k, v in ROOM.items() if k != CONF_ROOM_FIL_PILOTE_ENTITY}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], payload)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_ROOM_FIL_PILOTE_ENTITY] == "actuator_required"


async def test_from_area_prefills_the_form(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    salon = area_registry.async_get(hass).async_create("Salon")

    result = await _init_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "from_area"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "from_area"

    # Empty area still resolves: no discovery data, but the form is shown.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_ROOM_AREA: salon.id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**ROOM, CONF_ROOM_AREA: salon.id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salon"
    assert result["data"][CONF_ROOM_AREA] == salon.id
    assert result["data"][CONF_ROOM_NAME] == "Salon"
    assert result["data"][CONF_ROOM_TEMP_ENTITY] == ROOM[CONF_ROOM_TEMP_ENTITY]
