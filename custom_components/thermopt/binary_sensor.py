"""Binary sensors: degradation flag, tariff state and per-room health."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ThermOptEntity, ThermOptRoomEntity, description_name, hub_device_info
from .runtime import ThermOptRuntime
from .settings import RoomConfig


@dataclass(frozen=True, kw_only=True)
class SystemBinaryDescription(BinarySensorEntityDescription):
    """System-wide binary sensor."""

    value_fn: Any = None


SYSTEM_BINARY: tuple[SystemBinaryDescription, ...] = (
    SystemBinaryDescription(
        key="degraded",
        name="Mode dégradé",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: bool(data.degraded),
    ),
    SystemBinaryDescription(
        key="heures_creuses",
        name="Heures creuses",
        icon="mdi:clock-fast",
        value_fn=lambda data: data.is_hc,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ThermOptRuntime = entry.runtime_data

    entities: list[Any] = [ThermOptSystemBinary(runtime, desc) for desc in SYSTEM_BINARY]
    entities.extend(ThermOptRoomProblem(runtime, room.config) for room in runtime.rooms.values())
    async_add_entities(entities)


class ThermOptSystemBinary(ThermOptEntity, BinarySensorEntity):
    """System-wide binary sensor."""

    entity_description: SystemBinaryDescription

    def __init__(self, runtime: ThermOptRuntime, description: SystemBinaryDescription) -> None:
        super().__init__(runtime, description.key)
        self.entity_description = description
        self._attr_name = description_name(description)
        self._attr_device_info = hub_device_info(runtime)

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        return bool(self.entity_description.value_fn(data))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or self.entity_description.key != "degraded":
            return None
        return {
            "reasons": list(data.degraded),
            "forecast_source": data.forecast_source,
            "next_transition": (data.next_transition.isoformat() if data.next_transition else None),
        }


class ThermOptRoomProblem(ThermOptRoomEntity, BinarySensorEntity):
    """Per-room health, fed by the liveness checks."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Problème"

    def __init__(self, runtime: ThermOptRuntime, config: RoomConfig) -> None:
        super().__init__(runtime, config, "problem")

    @property
    def is_on(self) -> bool | None:
        room = self.room
        if room is None:
            return None
        return bool(room.degraded)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        room = self.room
        if room is None:
            return None
        return {"reasons": list(room.degraded)}
