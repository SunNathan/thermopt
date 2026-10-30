"""Shared entity plumbing."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, NAME
from .coordinator import RoomSnapshot, ThermOptCoordinator
from .runtime import ThermOptRuntime
from .settings import RoomConfig


def description_name(description: EntityDescription) -> str | None:
    """Return the description's name when it is a plain string.

    ``EntityDescription.name`` is typed ``str | UndefinedType | None``; our
    descriptions always carry a string, but the type system cannot know it.
    """
    name = description.name
    return name if isinstance(name, str) else None


def hub_device_info(runtime: ThermOptRuntime) -> DeviceInfo:
    """Device grouping the system-wide entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, runtime.entry.entry_id)},
        name=NAME,
        manufacturer=MANUFACTURER,
        model=MODEL,
        entry_type=DeviceEntryType.SERVICE,
        sw_version=runtime.version,
    )


def room_device_info(runtime: ThermOptRuntime, config: RoomConfig) -> DeviceInfo:
    """One device per heated room."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{runtime.entry.entry_id}_{config.subentry_id}")},
        name=config.name,
        manufacturer=MANUFACTURER,
        model="Radiateur piloté",
        via_device=(DOMAIN, runtime.entry.entry_id),
    )


class ThermOptEntity(CoordinatorEntity[ThermOptCoordinator]):
    """Base class for all ThermOpt entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: ThermOptRuntime, key: str) -> None:
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_{key}"

    @property
    def available(self) -> bool:
        return super().available


class ThermOptRoomEntity(ThermOptEntity):
    """Base class for per-room entities."""

    def __init__(self, runtime: ThermOptRuntime, config: RoomConfig, key: str) -> None:
        super().__init__(runtime, f"{config.subentry_id}_{key}")
        self.room_config = config
        self._attr_device_info = room_device_info(runtime, config)

    @property
    def room(self) -> RoomSnapshot | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.rooms.get(self.room_config.subentry_id)
