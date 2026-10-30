"""MQTT discovery payloads.

Pure Python: no network, no Home Assistant import. Keeping the payloads free of
dependencies makes them testable without a broker or a running app.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "thermopt"
DEVICE_ID = "thermopt_app"
MANUFACTURER = "ThermOpt"
MODEL = "Supervision chauffage fil pilote"

AVAILABILITY_TOPIC = f"{BASE_TOPIC}/app/availability"
PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"

HEALTH_STATE_TOPIC = f"{BASE_TOPIC}/app/state"
HEALTH_ATTRIBUTES_TOPIC = f"{BASE_TOPIC}/app/attributes"

MODE_OPTIONS = ("observation", "actif", "repli")


def slugify(value: str) -> str:
    """ASCII slug, safe for entity ids and MQTT topics."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "piece"


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
def build_device(version: str) -> dict:
    """Device block shared by every system entity."""
    return {
        "identifiers": [DEVICE_ID],
        "name": "ThermOpt",
        "manufacturer": MANUFACTURER,
        "model": MODEL,
        "sw_version": version,
    }


def build_room_device(room_id: str, name: str) -> dict:
    """One device per room, attached to the app device."""
    return {
        "identifiers": [f"thermopt_room_{room_id}"],
        "name": name or f"Pièce {room_id}",
        "manufacturer": MANUFACTURER,
        "model": "Pièce chauffée",
        "via_device": DEVICE_ID,
    }


# ---------------------------------------------------------------------------
# Generic payloads
# ---------------------------------------------------------------------------
def sensor_config(
    *,
    name: str,
    unique_id: str,
    object_id: str,
    state_topic: str,
    device: dict,
    device_class: str | None = None,
    unit: str | None = None,
    icon: str | None = None,
    attributes_topic: str | None = None,
    options: tuple[str, ...] | None = None,
    state_class: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": unique_id,
        "object_id": object_id,
        "state_topic": state_topic,
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": PAYLOAD_ONLINE,
        "payload_not_available": PAYLOAD_OFFLINE,
        "device": device,
    }
    if device_class:
        payload["device_class"] = device_class
    if unit:
        payload["unit_of_measurement"] = unit
    if icon:
        payload["icon"] = icon
    if attributes_topic:
        payload["json_attributes_topic"] = attributes_topic
    if options:
        payload["options"] = list(options)
    if state_class:
        payload["state_class"] = state_class
    return payload


def binary_config(
    *,
    name: str,
    unique_id: str,
    object_id: str,
    state_topic: str,
    device: dict,
    device_class: str | None = None,
    icon: str | None = None,
    attributes_topic: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": unique_id,
        "object_id": object_id,
        "state_topic": state_topic,
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": PAYLOAD_ONLINE,
        "payload_not_available": PAYLOAD_OFFLINE,
        "device": device,
    }
    if device_class:
        payload["device_class"] = device_class
    if icon:
        payload["icon"] = icon
    if attributes_topic:
        payload["json_attributes_topic"] = attributes_topic
    return payload


def config_topic(component: str, key: str) -> str:
    """Retained discovery topic, e.g. ``homeassistant/sensor/thermopt_status/config``."""
    return f"{DISCOVERY_PREFIX}/{component}/thermopt_{key}/config"


# ---------------------------------------------------------------------------
# Entity tables
# ---------------------------------------------------------------------------
SYSTEM_TOPICS = {
    "status": f"{BASE_TOPIC}/status",
    "degraded": f"{BASE_TOPIC}/degraded",
    "price": f"{BASE_TOPIC}/price",
    "last_cycle": f"{BASE_TOPIC}/last_cycle",
}
SYSTEM_ATTRIBUTES = {
    "degraded": f"{BASE_TOPIC}/degraded/attributes",
}

ROOM_KEYS = ("temperature", "target_min", "safety", "applied_order", "power", "plan_cost")


def room_topic(room_id: str, key: str) -> str:
    return f"{BASE_TOPIC}/rooms/{room_id}/{key}"


def room_attributes_topic(room_id: str, key: str) -> str:
    return f"{BASE_TOPIC}/rooms/{room_id}/{key}/attributes"


def system_entities(version: str) -> list[tuple[str, str, dict]]:
    """``(component, key, payload)`` for the app-wide entities."""
    device = build_device(version)
    return [
        (
            "sensor",
            "status",
            sensor_config(
                name="Statut",
                unique_id=f"{DEVICE_ID}_status",
                object_id="thermopt_statut",
                state_topic=SYSTEM_TOPICS["status"],
                device=device,
                device_class="enum",
                options=MODE_OPTIONS,
                icon="mdi:state-machine",
            ),
        ),
        (
            "binary_sensor",
            "degraded",
            binary_config(
                name="Mode dégradé",
                unique_id=f"{DEVICE_ID}_degraded",
                object_id="thermopt_mode_degrade",
                state_topic=SYSTEM_TOPICS["degraded"],
                device=device,
                device_class="problem",
                attributes_topic=SYSTEM_ATTRIBUTES["degraded"],
            ),
        ),
        (
            "sensor",
            "price",
            sensor_config(
                name="Prix actuel",
                unique_id=f"{DEVICE_ID}_price",
                object_id="thermopt_prix_actuel",
                state_topic=SYSTEM_TOPICS["price"],
                device=device,
                unit="€/kWh",
                icon="mdi:currency-eur",
                state_class="measurement",
            ),
        ),
        (
            "sensor",
            "last_cycle",
            sensor_config(
                name="Dernier cycle",
                unique_id=f"{DEVICE_ID}_last_cycle",
                object_id="thermopt_dernier_cycle",
                state_topic=SYSTEM_TOPICS["last_cycle"],
                device=device,
                device_class="timestamp",
            ),
        ),
    ]


def room_entities(room_id: str, name: str, version: str) -> list[tuple[str, str, dict]]:
    """``(component, key, payload)`` for one room."""
    device = build_room_device(room_id, name)
    slug = slugify(name)
    unique = f"thermopt_room_{room_id}"
    entities: list[tuple[str, str, dict]] = []

    for key, label, unit, device_class, icon in (
        ("temperature", "Température mesurée", "°C", "temperature", None),
        ("target_min", "Consigne minimale", "°C", "temperature", "mdi:thermometer-low"),
        ("power", "Puissance", "W", "power", None),
    ):
        entities.append(
            (
                "sensor",
                f"{room_id}_{key}",
                sensor_config(
                    name=label,
                    unique_id=f"{unique}_{key}",
                    object_id=f"thermopt_{slug}_{key}",
                    state_topic=room_topic(room_id, key),
                    device=device,
                    device_class=device_class,
                    unit=unit,
                    icon=icon,
                    state_class="measurement",
                ),
            )
        )

    entities.append(
        (
            "sensor",
            f"{room_id}_safety",
            sensor_config(
                name="Sécurité",
                unique_id=f"{unique}_safety",
                object_id=f"thermopt_{slug}_securite",
                state_topic=room_topic(room_id, "safety"),
                device=device,
                icon="mdi:shield-check",
                attributes_topic=room_attributes_topic(room_id, "safety"),
            ),
        )
    )

    entities.append(
        (
            "sensor",
            f"{room_id}_prediction",
            sensor_config(
                name="Température prévue à 12 h",
                unique_id=f"{unique}_prediction",
                object_id=f"thermopt_{slug}_temperature_prevue_12h",
                state_topic=room_topic(room_id, "prediction"),
                device=device,
                device_class="temperature",
                unit="°C",
                icon="mdi:crystal-ball",
            ),
        )
    )

    entities.append(
        (
            "sensor",
            f"{room_id}_applied_order",
            sensor_config(
                name="Ordre appliqué",
                unique_id=f"{unique}_applied_order",
                object_id=f"thermopt_{slug}_ordre_applique",
                state_topic=room_topic(room_id, "applied_order"),
                device=device,
                icon="mdi:radiator",
                attributes_topic=room_attributes_topic(room_id, "applied_order"),
            ),
        )
    )

    entities.append(
        (
            "sensor",
            f"{room_id}_plan_cost",
            sensor_config(
                name="Coût prévu 24 h",
                unique_id=f"{unique}_plan_cost",
                object_id=f"thermopt_{slug}_cout_24h",
                state_topic=room_topic(room_id, "plan_cost"),
                device=device,
                unit="€",
                icon="mdi:currency-eur",
                state_class="measurement",
            ),
        )
    )

    entities.append(
        (
            "sensor",
            f"{room_id}_next_action",
            sensor_config(
                name="Prochaine action",
                unique_id=f"{unique}_next_action",
                object_id=f"thermopt_{slug}_prochaine_action",
                state_topic=room_topic(room_id, "next_action"),
                device=device,
                icon="mdi:radiator",
            ),
        )
    )

    return entities


# ---------------------------------------------------------------------------
# Legacy health entity (milestone A)
# ---------------------------------------------------------------------------
def build_health_config(version: str) -> dict:
    """Discovery payload for ``sensor.thermopt_app``."""
    return {
        "name": "Application",
        "unique_id": f"{DEVICE_ID}_health",
        "object_id": f"{DEVICE_ID}_app",
        "icon": "mdi:home-thermometer",
        "state_topic": HEALTH_STATE_TOPIC,
        "json_attributes_topic": HEALTH_ATTRIBUTES_TOPIC,
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": PAYLOAD_ONLINE,
        "payload_not_available": PAYLOAD_OFFLINE,
        "device": build_device(version),
    }


def health_config_topic() -> str:
    """Retained discovery topic for the health sensor."""
    return f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}_health/config"
