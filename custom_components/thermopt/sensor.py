"""Sensors: supervisor status, cycle heartbeat, tariff and per-room values."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import RoomSnapshot, ThermOptData
from .core.orders import LABELS_FR
from .entity import ThermOptEntity, ThermOptRoomEntity, hub_device_info
from .runtime import ThermOptRuntime
from .settings import RoomConfig

CURRENCY_PER_KWH = "€/kWh"


@dataclass(frozen=True, kw_only=True)
class SystemSensorDescription(SensorEntityDescription):
    """System-wide sensor."""

    value_fn: Callable[[ThermOptData], Any]


@dataclass(frozen=True, kw_only=True)
class RoomSensorDescription(SensorEntityDescription):
    """Per-room sensor."""

    value_fn: Callable[[RoomSnapshot], Any]


SYSTEM_SENSORS: tuple[SystemSensorDescription, ...] = (
    SystemSensorDescription(
        key="status",
        name="Statut",
        icon="mdi:state-machine",
        value_fn=lambda data: data.status,
    ),
    SystemSensorDescription(
        key="last_cycle",
        name="Dernier cycle",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.last_cycle,
    ),
    SystemSensorDescription(
        key="next_cycle",
        name="Prochain cycle",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.next_cycle,
    ),
    SystemSensorDescription(
        key="price",
        name="Prix actuel",
        native_unit_of_measurement=CURRENCY_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:currency-eur",
        value_fn=lambda data: data.price_now,
    ),
    SystemSensorDescription(
        key="outdoor",
        name="Température extérieure",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.outdoor_now,
    ),
)

ROOM_SENSORS: tuple[RoomSensorDescription, ...] = (
    RoomSensorDescription(
        key="temperature",
        name="Température mesurée",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda room: room.t_air,
    ),
    RoomSensorDescription(
        key="humidity",
        name="Humidité mesurée",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda room: room.humidity,
    ),
    RoomSensorDescription(
        key="target_min",
        name="Consigne minimale",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        icon="mdi:thermometer-low",
        value_fn=lambda room: room.target_min,
    ),
    RoomSensorDescription(
        key="target_max",
        name="Consigne maximale",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        icon="mdi:thermometer-high",
        value_fn=lambda room: room.target_max,
    ),
    RoomSensorDescription(
        key="slot",
        name="Créneau",
        icon="mdi:clock-outline",
        value_fn=lambda room: room.slot,
    ),
    RoomSensorDescription(
        key="order",
        name="Ordre fil pilote",
        icon="mdi:radiator",
        value_fn=lambda room: room.order.value if room.order else None,
    ),
    RoomSensorDescription(
        key="power",
        name="Puissance",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda room: room.power,
    ),
    RoomSensorDescription(
        key="energy",
        name="Énergie",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda room: room.energy,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ThermOptRuntime = entry.runtime_data

    entities: list[Any] = [ThermOptSystemSensor(runtime, desc) for desc in SYSTEM_SENSORS]
    for config in (room.config for room in runtime.rooms.values()):
        entities.extend(ThermOptRoomSensor(runtime, config, desc) for desc in ROOM_SENSORS)

    async_add_entities(entities)


class ThermOptSystemSensor(ThermOptEntity, SensorEntity):
    """System-wide sensor driven by the coordinator payload."""

    entity_description: SystemSensorDescription

    def __init__(self, runtime: ThermOptRuntime, description: SystemSensorDescription) -> None:
        super().__init__(runtime, description.key)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_device_info = hub_device_info(runtime)

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or self.entity_description.key != "status":
            return None
        return {"degraded": list(data.degraded)}


class ThermOptRoomSensor(ThermOptRoomEntity, SensorEntity):
    """Per-room sensor."""

    entity_description: RoomSensorDescription

    def __init__(
        self,
        runtime: ThermOptRuntime,
        config: RoomConfig,
        description: RoomSensorDescription,
    ) -> None:
        super().__init__(runtime, config, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def native_value(self) -> Any:
        room = self.room
        if room is None:
            return None
        return self.entity_description.value_fn(room)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        room = self.room
        if room is None:
            return None
        if self.entity_description.key != "order":
            return None
        return {
            "label": LABELS_FR.get(room.order) if room.order else None,
            "degraded": list(room.degraded),
        }
