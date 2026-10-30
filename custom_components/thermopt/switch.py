"""Per-room enable switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ThermOptRoomEntity
from .runtime import ThermOptRuntime
from .settings import RoomConfig


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ThermOptRuntime = entry.runtime_data
    async_add_entities(
        ThermOptRoomEnabledSwitch(runtime, room.config) for room in runtime.rooms.values()
    )


class ThermOptRoomEnabledSwitch(ThermOptRoomEntity, SwitchEntity):
    """Take a room in or out of supervision."""

    _attr_name = "Supervision active"
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, runtime: ThermOptRuntime, config: RoomConfig) -> None:
        super().__init__(runtime, config, "enabled")

    @property
    def is_on(self) -> bool:
        room = self.runtime.rooms.get(self.room_config.subentry_id)
        return bool(room and room.enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.runtime.async_set_room_enabled(self.room_config.subentry_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.runtime.async_set_room_enabled(self.room_config.subentry_id, False)
        self.async_write_ha_state()
