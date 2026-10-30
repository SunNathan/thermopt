"""Tests for the app configuration model and its validation."""

from __future__ import annotations

from app.config import AppConfig, RoomConfig, ladder_rows, profile_summary, validate
from app.discovery import (
    build_device,
    build_room_device,
    config_topic,
    room_entities,
    room_topic,
    slugify,
    system_entities,
)

ROOM = RoomConfig(
    id="abc123",
    name="Salon",
    temp_entity="sensor.salon_temperature",
    fil_pilote_entity="select.salon_pilot_wire_mode",
)


def _config(**overrides) -> AppConfig:
    base = {"rooms": (ROOM,)}
    base.update(overrides)
    return AppConfig(**base)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def test_roundtrip() -> None:
    config = _config(hc_windows="22:00-06:00, 12:00-14:00")
    restored = AppConfig.from_dict(config.to_dict())

    assert restored.rooms == config.rooms
    assert restored.hc_windows == config.hc_windows
    assert restored.comfort_setpoint == config.comfort_setpoint


def test_empty_dict_gives_defaults() -> None:
    config = AppConfig.from_dict(None)
    assert config.rooms == ()
    assert config.comfort_setpoint == 20.5
    assert config.active is True


def test_with_room_adds_and_replaces() -> None:
    config = _config()
    other = RoomConfig(id="zzz", name="Chambre")

    assert len(config.with_room(other).rooms) == 2
    replaced = config.with_room(RoomConfig(id=ROOM.id, name="Salon 2"))
    assert len(replaced.rooms) == 1
    assert replaced.rooms[0].name == "Salon 2"


def test_without_room() -> None:
    assert _config().without_room(ROOM.id).rooms == ()


def test_ladder_and_profile_derived() -> None:
    config = _config(comfort_setpoint=20.5)
    assert config.ladder.setpoint.__self__ is not None
    assert config.profile.starts["night"] == 23 * 60
    assert dict(ladder_rows(config))["Eco"] == 17.0
    assert len(profile_summary(config)) == 4


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_valid_config_has_no_error() -> None:
    assert validate(_config()) == []


def test_no_room_is_rejected() -> None:
    assert any("Aucune pièce" in e for e in validate(AppConfig()))


def test_missing_actuator_is_rejected() -> None:
    room = RoomConfig(id="x", name="Salon", temp_entity="sensor.t")
    errors = validate(AppConfig(rooms=(room,)))
    assert any("fil pilote" in e for e in errors)


def test_missing_name_is_rejected() -> None:
    room = RoomConfig(id="x", name="  ", temp_entity="sensor.t", fil_pilote_entity="select.f")
    assert any("nom" in e for e in validate(AppConfig(rooms=(room,))))


def test_invalid_windows_are_rejected() -> None:
    errors = validate(_config(hc_windows="n'importe quoi"))
    assert any("Heures Creuses" in e for e in errors)


def test_frost_too_high_is_rejected() -> None:
    errors = validate(_config(comfort_setpoint=20.0, frost_setpoint=18.0))
    assert any("Hors-gel" in e for e in errors)


def test_profile_unreachable_is_explained_with_numbers() -> None:
    """The C = 20 °C trap must produce an actionable message."""
    errors = validate(_config(comfort_setpoint=20.0))
    assert any("20,5" in error for error in errors), errors


def test_duplicate_room_id_is_rejected() -> None:
    twin = RoomConfig(
        id=ROOM.id, name="Salon bis", temp_entity="sensor.t2", fil_pilote_entity="select.f2"
    )
    errors = validate(AppConfig(rooms=(ROOM, twin)))
    assert any("dupliqué" in e for e in errors)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def test_slugify() -> None:
    assert slugify("Chambre d'amis") == "chambre_d_amis"
    assert slugify("Étage 1") == "etage_1"
    assert slugify("") == "piece"


def test_room_entities_are_complete() -> None:
    entities = room_entities(ROOM.id, ROOM.name, "0.3.0")
    keys = {key for _component, key, _payload in entities}

    assert keys == {
        f"{ROOM.id}_temperature",
        f"{ROOM.id}_target_min",
        f"{ROOM.id}_power",
        f"{ROOM.id}_safety",
        f"{ROOM.id}_applied_order",
        f"{ROOM.id}_prediction",
        f"{ROOM.id}_plan_cost",
        f"{ROOM.id}_next_action",
    }

    payload = next(p for _c, k, p in entities if k.endswith("temperature"))
    assert payload["object_id"] == "thermopt_salon_temperature"
    assert payload["unit_of_measurement"] == "°C"
    assert payload["device"]["identifiers"] == [f"thermopt_room_{ROOM.id}"]
    assert payload["device"]["via_device"] == "thermopt_app"


def test_room_topics_are_unique() -> None:
    assert room_topic("abc", "temperature") == "thermopt/rooms/abc/temperature"


def test_system_entities_have_object_ids() -> None:
    entities = system_entities("0.3.0")
    object_ids = {payload["object_id"] for _c, _k, payload in entities}
    assert "thermopt_statut" in object_ids
    assert "thermopt_mode_degrade" in object_ids
    assert "thermopt_dernier_cycle" in object_ids


def test_config_topics() -> None:
    assert config_topic("sensor", "thermopt_status").endswith("/config")


def test_devices() -> None:
    hub = build_device("0.3.0")
    room = build_room_device("abc", "Salon")
    assert hub["identifiers"] == ["thermopt_app"]
    assert room["via_device"] == hub["identifiers"][0]
