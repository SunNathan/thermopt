"""MQTT discovery payloads.

Pure Python: no network, no Home Assistant import. Keeping this module free of
dependencies makes the payloads testable without a broker.
"""

from __future__ import annotations

DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "thermopt"
DEVICE_ID = "thermopt_app"
MANUFACTURER = "ThermOpt"
MODEL = "Supervision chauffage fil pilote"

HEALTH_STATE_TOPIC = f"{BASE_TOPIC}/app/state"
HEALTH_ATTRIBUTES_TOPIC = f"{BASE_TOPIC}/app/attributes"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/app/availability"

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"


def build_device(version: str) -> dict:
    """Device block shared by every entity published by the app."""
    return {
        "identifiers": [DEVICE_ID],
        "name": "ThermOpt",
        "manufacturer": MANUFACTURER,
        "model": MODEL,
        "sw_version": version,
    }


def build_health_config(version: str) -> dict:
    """Discovery payload for ``sensor.thermopt_app``.

    This entity exists to prove the whole chain in milestone A: install,
    Supervisor proxy, MQTT discovery, availability. It will be joined by the
    real sensors later.
    """
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
