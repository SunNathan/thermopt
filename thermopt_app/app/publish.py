"""Publish ThermOpt state to MQTT, using the discovery payloads."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from thermopt_lib.core.orders import LABELS_FR, Order

from .config import AppConfig
from .discovery import (
    SYSTEM_ATTRIBUTES,
    SYSTEM_TOPICS,
    config_topic,
    room_attributes_topic,
    room_entities,
    room_topic,
)
from .mqtt import MqttPublisher

_LOGGER = logging.getLogger(__name__)

UNKNOWN = "unknown"


@dataclass(slots=True)
class RoomState:
    """What the room looks like right now."""

    id: str
    name: str
    temperature: float | None = None
    target_min: float | None = None
    safety: str = "inactif"
    safety_reason: str = ""
    applied_order: Order | None = None
    order_source: str = "inconnue"
    power: float | None = None
    prediction: float | None = None


@dataclass(slots=True)
class Snapshot:
    """Everything published on one cycle."""

    mode: str = "observation"
    degraded: bool = False
    details: list[str] = field(default_factory=list)
    price: float | None = None
    last_cycle: str | None = None
    rooms: list[RoomState] = field(default_factory=list)


def _number(value: float | None) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:.2f}".rstrip("0").rstrip(".")


class Publisher:
    """Announce the entities once, then keep their states up to date."""

    def __init__(self, mqtt: MqttPublisher, version: str) -> None:
        self._mqtt = mqtt
        self._version = version

    async def publish_discovery(self, config: AppConfig) -> None:
        from .discovery import system_entities

        for component, key, payload in system_entities(self._version):
            await self._mqtt.publish_json(config_topic(component, key), payload)

        for room in config.rooms:
            for component, key, payload in room_entities(room.id, room.name, self._version):
                await self._mqtt.publish_json(config_topic(component, key), payload)

    async def publish_state(self, snapshot: Snapshot) -> None:
        await self._mqtt.publish(SYSTEM_TOPICS["status"], snapshot.mode)
        await self._mqtt.publish(SYSTEM_TOPICS["degraded"], "ON" if snapshot.degraded else "OFF")
        await self._mqtt.publish_json(
            SYSTEM_ATTRIBUTES["degraded"],
            {"reasons": snapshot.details},
        )
        if snapshot.price is not None:
            await self._mqtt.publish(SYSTEM_TOPICS["price"], _number(snapshot.price))
        if snapshot.last_cycle:
            await self._mqtt.publish(SYSTEM_TOPICS["last_cycle"], snapshot.last_cycle)

        for room in snapshot.rooms:
            await self._mqtt.publish(room_topic(room.id, "temperature"), _number(room.temperature))
            await self._mqtt.publish(room_topic(room.id, "target_min"), _number(room.target_min))
            await self._mqtt.publish(room_topic(room.id, "power"), _number(room.power))
            if room.prediction is not None:
                await self._mqtt.publish(
                    room_topic(room.id, "prediction"), _number(room.prediction)
                )
            await self._mqtt.publish(room_topic(room.id, "safety"), room.safety)
            await self._mqtt.publish_json(
                room_attributes_topic(room.id, "safety"),
                {"raison": room.safety_reason},
            )
            await self._mqtt.publish(
                room_topic(room.id, "applied_order"),
                room.applied_order.value if room.applied_order else UNKNOWN,
            )
            await self._mqtt.publish_json(
                room_attributes_topic(room.id, "applied_order"),
                {
                    "libelle": LABELS_FR.get(room.applied_order) if room.applied_order else None,
                    "source": room.order_source,
                },
            )
