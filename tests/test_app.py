"""Tests for the app skeleton: options parsing and MQTT discovery payloads."""

from __future__ import annotations

import json

from app.discovery import (
    AVAILABILITY_TOPIC,
    DEVICE_ID,
    HEALTH_ATTRIBUTES_TOPIC,
    HEALTH_STATE_TOPIC,
    build_device,
    build_health_config,
    health_config_topic,
)
from app.options import Options

VERSION = "0.2.0"


def test_health_config_topic() -> None:
    assert health_config_topic() == f"homeassistant/sensor/{DEVICE_ID}_health/config"


def test_health_payload_shape() -> None:
    payload = build_health_config(VERSION)

    assert payload["unique_id"] == f"{DEVICE_ID}_health"
    assert payload["state_topic"] == HEALTH_STATE_TOPIC
    assert payload["json_attributes_topic"] == HEALTH_ATTRIBUTES_TOPIC
    assert payload["availability_topic"] == AVAILABILITY_TOPIC
    assert payload["payload_available"] == "online"
    assert payload["payload_not_available"] == "offline"


def test_device_block_carries_the_version() -> None:
    device = build_device(VERSION)

    assert device["identifiers"] == [DEVICE_ID]
    assert device["sw_version"] == VERSION
    assert device["name"] == "ThermOpt"


def test_payload_is_json_serialisable() -> None:
    """A payload that cannot be sent is worse than no payload."""
    encoded = json.dumps(build_health_config(VERSION))
    assert VERSION in encoded


def test_options_defaults_without_payload() -> None:
    assert Options.parse(None).log_level == "info"
    assert Options.parse({}).log_level == "info"


def test_options_reject_unknown_level() -> None:
    assert Options.parse({"log_level": "nope"}).log_level == "info"


def test_options_are_case_insensitive() -> None:
    assert Options.parse({"log_level": "DEBUG"}).log_level == "debug"


def test_options_load_missing_file(tmp_path) -> None:
    """A missing options file must not prevent the app from starting."""
    assert Options.load(tmp_path / "absent.json").log_level == "info"


def test_options_load_invalid_json(tmp_path) -> None:
    path = tmp_path / "options.json"
    path.write_text("{not json", encoding="utf-8")
    assert Options.load(path).log_level == "info"


def test_options_load_valid_file(tmp_path) -> None:
    path = tmp_path / "options.json"
    path.write_text('{"log_level": "warning"}', encoding="utf-8")
    assert Options.load(path).log_level == "warning"
