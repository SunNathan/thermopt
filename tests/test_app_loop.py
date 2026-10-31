"""Tests for the supervision loop: modes, order restitution and overrides."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.config import AppConfig, RoomConfig
from app.ha import EntityState
from app.loop import SupervisionLoop
from thermopt_lib.core.orders import Order
from thermopt_lib.perception.comfort import (
    SLOT_DAY,
    SLOT_EVENING,
    SLOT_MORNING,
    SLOT_NIGHT,
    ComfortProfile,
)


class _Ha:
    """Minimal stand-in: the mode logic only reads the state cache."""

    def __init__(self, states: dict | None = None) -> None:
        self._states = states or {}

    def cached(self) -> dict:
        return self._states


def _loop(config: AppConfig, states: dict | None = None) -> SupervisionLoop:
    return SupervisionLoop(_Ha(states), None, config, UTC, None)  # type: ignore[arg-type]


def test_mode_is_actif_when_enabled() -> None:
    loop = _loop(AppConfig(active=True))
    loop.refresh_mode()
    assert loop.mode == "actif"


def test_mode_follows_the_configuration_immediately() -> None:
    """Pressing "observation" must not wait for the next cycle."""
    loop = _loop(AppConfig(active=True))
    loop.refresh_mode()
    assert loop.mode == "actif"

    loop.apply_config(replace(loop._config, active=False))
    assert loop.mode == "observation"

    loop.apply_config(replace(loop._config, active=True))
    assert loop.mode == "actif"


def test_mode_reports_the_fallback() -> None:
    from app.ha import EntityState

    states = {"input_boolean.thermopt_repli": EntityState("input_boolean.thermopt_repli", "on", {})}
    loop = _loop(AppConfig(active=True), states)
    loop.refresh_mode()
    assert loop.mode == "repli"


def test_observation_wins_over_the_fallback() -> None:
    from app.ha import EntityState

    states = {"input_boolean.thermopt_repli": EntityState("input_boolean.thermopt_repli", "on", {})}
    loop = _loop(AppConfig(active=False), states)
    loop.refresh_mode()
    assert loop.mode == "observation"


# ---------------------------------------------------------------------------
# Order restitution (Comfort -> Eco at night, without the optimiser)
# ---------------------------------------------------------------------------
NOW = datetime(2026, 1, 5, 23, 30, tzinfo=UTC)  # Monday, 23:30
PROFILE = ComfortProfile(
    weekday={SLOT_NIGHT: 17.5, SLOT_MORNING: 19.5, SLOT_DAY: 17.5, SLOT_EVENING: 19.5},
    weekend={SLOT_NIGHT: 17.5, SLOT_MORNING: 19.5, SLOT_DAY: 19.5, SLOT_EVENING: 19.5},
)
ROOM = RoomConfig(
    id="salon",
    name="Salon",
    temp_entity="sensor.salon_temperature",
    power_entity="sensor.salon_power",
    fil_pilote_entity="select.salon_pilot_wire_mode",
)


class _RoomHa:
    """Enough of HaClient for one room cycle."""

    def __init__(self, order: str = "comfort", temperature: float = 20.0) -> None:
        self._states = {
            ROOM.fil_pilote_entity: EntityState(ROOM.fil_pilote_entity or "", order, {}),
        }
        self._values = {
            ROOM.temp_entity: temperature,
            ROOM.power_entity: 0.0,
        }
        self.writes: list[tuple[str, str]] = []

    def cached(self) -> dict:
        return self._states

    async def numeric(self, entity_id: str | None) -> float | None:
        return self._values.get(entity_id)  # type: ignore[arg-type]

    async def select_option(self, entity_id: str, option: str) -> None:
        self.writes.append((entity_id, option))


def _room_loop(ha: _RoomHa, **overrides) -> SupervisionLoop:
    values = {"rooms": (ROOM,), "active": True, "comfort_setpoint": 20.5}
    values.update(overrides)
    config = AppConfig(**values)
    return SupervisionLoop(ha, None, config, UTC, None)  # type: ignore[arg-type]


async def test_comfort_is_lowered_to_eco_when_the_night_floor_drops() -> None:
    """The reported bug: Comfort stayed on all night after a guard."""
    ha = _RoomHa(order="comfort", temperature=20.0)
    loop = _room_loop(ha)
    room = loop.rooms[ROOM.id]
    room.last_written = Order.COMFORT
    room.last_write_at = NOW - timedelta(hours=1)
    room.guard_armed = True

    await loop._process_room(room, NOW, PROFILE, True)

    assert ha.writes == [(ROOM.fil_pilote_entity, "eco")]
    assert room.last_written is Order.ECO


async def test_an_order_written_elsewhere_is_overridden() -> None:
    """Active mode is authoritative: no ownership check any more."""
    ha = _RoomHa(order="comfort", temperature=20.0)
    loop = _room_loop(ha)
    room = loop.rooms[ROOM.id]
    room.last_written = None
    room.last_write_at = NOW - timedelta(hours=1)

    await loop._process_room(room, NOW, PROFILE, True)

    assert ha.writes == [(ROOM.fil_pilote_entity, "eco")]


async def test_the_profile_raises_the_order_in_the_morning() -> None:
    ha = _RoomHa(order="eco", temperature=19.0)
    loop = _room_loop(ha)
    room = loop.rooms[ROOM.id]
    room.last_written = Order.ECO
    room.last_write_at = NOW - timedelta(hours=8)
    morning = datetime(2026, 1, 6, 7, 0, tzinfo=UTC)

    await loop._process_room(room, morning, PROFILE, True)

    assert ha.writes == [(ROOM.fil_pilote_entity, "comfort_-1")]
    assert room.last_written is Order.COMFORT_1


async def test_an_order_already_at_the_profile_is_adopted() -> None:
    ha = _RoomHa(order="eco", temperature=20.0)
    loop = _room_loop(ha)
    room = loop.rooms[ROOM.id]

    await loop._process_room(room, NOW, PROFILE, True)

    assert ha.writes == []
    assert room.last_written is Order.ECO


async def test_observation_mode_writes_nothing() -> None:
    ha = _RoomHa(order="comfort", temperature=20.0)
    loop = _room_loop(ha, active=False)
    room = loop.rooms[ROOM.id]

    await loop._process_room(room, NOW, PROFILE, False)

    assert ha.writes == []


async def test_the_guard_keeps_priority_over_the_profile() -> None:
    ha = _RoomHa(order="eco", temperature=16.0)
    loop = _room_loop(ha)
    room = loop.rooms[ROOM.id]
    room.last_write_at = NOW - timedelta(hours=1)

    await loop._process_room(room, NOW, PROFILE, True)

    assert ha.writes == [(ROOM.fil_pilote_entity, "comfort")]


async def test_the_rate_limit_still_applies() -> None:
    ha = _RoomHa(order="comfort", temperature=20.0)
    loop = _room_loop(ha)
    room = loop.rooms[ROOM.id]
    room.last_written = Order.COMFORT
    room.last_write_at = NOW - timedelta(minutes=10)

    await loop._process_room(room, NOW, PROFILE, True)

    assert ha.writes == []
