"""Typed accessors for the config entry and its room subentries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import (
    CONF_AUTO_ENTITY,
    CONF_COMFORT_SETPOINT,
    CONF_FALLBACK_ENTITY,
    CONF_FROST_SETPOINT,
    CONF_HC_BINARY_ENTITY,
    CONF_HC_PRICE,
    CONF_HC_WINDOWS,
    CONF_HIGH_MARGIN,
    CONF_HP_PRICE,
    CONF_PRESENCE_ENTITY,
    CONF_ROOM_AREA,
    CONF_ROOM_ENERGY_ENTITY,
    CONF_ROOM_FIL_PILOTE_ENTITY,
    CONF_ROOM_HUMIDITY_ENTITY,
    CONF_ROOM_NAME,
    CONF_ROOM_NOMINAL_POWER,
    CONF_ROOM_POWER_ENTITY,
    CONF_ROOM_RELAY_ENTITY,
    CONF_ROOM_SURFACE,
    CONF_ROOM_TEMP_ENTITY,
    CONF_ROOM_VOLUME,
    CONF_START_DAY,
    CONF_START_EVENING,
    CONF_START_MORNING,
    CONF_START_NIGHT,
    CONF_T_MIN_DAY_WEEKDAY,
    CONF_T_MIN_DAY_WEEKEND,
    CONF_T_MIN_EVENING_WEEKDAY,
    CONF_T_MIN_EVENING_WEEKEND,
    CONF_T_MIN_MORNING_WEEKDAY,
    CONF_T_MIN_MORNING_WEEKEND,
    CONF_T_MIN_NIGHT_WEEKDAY,
    CONF_T_MIN_NIGHT_WEEKEND,
    CONF_T_MIN_PRESENT_DAY,
    CONF_TOLERANCE,
    CONF_WEATHER_ENTITY,
    DEFAULT_COMFORT_SETPOINT,
    DEFAULT_FALLBACK_ENTITY,
    DEFAULT_FROST_SETPOINT,
    DEFAULT_HC_PRICE,
    DEFAULT_HC_WINDOWS,
    DEFAULT_HP_PRICE,
    DEFAULT_NOMINAL_POWER,
    SUBENTRY_ROOM,
)
from .core.orders import Ladder
from .perception.comfort import (
    DEFAULT_HIGH_MARGIN,
    DEFAULT_PRESENT_DAY,
    DEFAULT_STARTS,
    DEFAULT_TOLERANCE,
    DEFAULT_WEEKDAY,
    DEFAULT_WEEKEND,
    SLOT_DAY,
    SLOT_EVENING,
    SLOT_MORNING,
    SLOT_NIGHT,
    ComfortProfile,
)
from .perception.tariff import Window, parse_windows


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class SystemConfig:
    """Resolved system configuration (config entry data + options)."""

    weather_entity: str | None = None
    hc_binary_entity: str | None = None
    presence_entity: str | None = None
    auto_entity: str | None = None
    fallback_entity: str = DEFAULT_FALLBACK_ENTITY
    hp_price: float = DEFAULT_HP_PRICE
    hc_price: float = DEFAULT_HC_PRICE
    ladder: Ladder = field(default_factory=Ladder)
    profile: ComfortProfile = field(default_factory=ComfortProfile)
    windows: tuple[Window, ...] = ()

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> SystemConfig:
        data: dict[str, Any] = {**entry.data, **entry.options}

        windows: tuple[Window, ...] = ()
        raw_windows = data.get(CONF_HC_WINDOWS, DEFAULT_HC_WINDOWS)
        try:
            windows = tuple(parse_windows(raw_windows))
        except Exception:  # noqa: BLE001 - invalid config must not crash setup
            windows = tuple(parse_windows(DEFAULT_HC_WINDOWS))

        profile = ComfortProfile.from_config(
            starts={
                SLOT_NIGHT: data.get(CONF_START_NIGHT, DEFAULT_STARTS[SLOT_NIGHT]),
                SLOT_MORNING: data.get(CONF_START_MORNING, DEFAULT_STARTS[SLOT_MORNING]),
                SLOT_DAY: data.get(CONF_START_DAY, DEFAULT_STARTS[SLOT_DAY]),
                SLOT_EVENING: data.get(CONF_START_EVENING, DEFAULT_STARTS[SLOT_EVENING]),
            },
            weekday={
                SLOT_NIGHT: _as_float(
                    data.get(CONF_T_MIN_NIGHT_WEEKDAY), DEFAULT_WEEKDAY[SLOT_NIGHT]
                ),
                SLOT_MORNING: _as_float(
                    data.get(CONF_T_MIN_MORNING_WEEKDAY), DEFAULT_WEEKDAY[SLOT_MORNING]
                ),
                SLOT_DAY: _as_float(data.get(CONF_T_MIN_DAY_WEEKDAY), DEFAULT_WEEKDAY[SLOT_DAY]),
                SLOT_EVENING: _as_float(
                    data.get(CONF_T_MIN_EVENING_WEEKDAY), DEFAULT_WEEKDAY[SLOT_EVENING]
                ),
            },
            weekend={
                SLOT_NIGHT: _as_float(
                    data.get(CONF_T_MIN_NIGHT_WEEKEND), DEFAULT_WEEKEND[SLOT_NIGHT]
                ),
                SLOT_MORNING: _as_float(
                    data.get(CONF_T_MIN_MORNING_WEEKEND), DEFAULT_WEEKEND[SLOT_MORNING]
                ),
                SLOT_DAY: _as_float(data.get(CONF_T_MIN_DAY_WEEKEND), DEFAULT_WEEKEND[SLOT_DAY]),
                SLOT_EVENING: _as_float(
                    data.get(CONF_T_MIN_EVENING_WEEKEND), DEFAULT_WEEKEND[SLOT_EVENING]
                ),
            },
            present_day=_as_float(data.get(CONF_T_MIN_PRESENT_DAY), DEFAULT_PRESENT_DAY),
            tolerance=_as_float(data.get(CONF_TOLERANCE), DEFAULT_TOLERANCE),
            high_margin=_as_float(data.get(CONF_HIGH_MARGIN), DEFAULT_HIGH_MARGIN),
        )

        return cls(
            weather_entity=data.get(CONF_WEATHER_ENTITY) or None,
            hc_binary_entity=data.get(CONF_HC_BINARY_ENTITY) or None,
            presence_entity=data.get(CONF_PRESENCE_ENTITY) or None,
            auto_entity=data.get(CONF_AUTO_ENTITY) or None,
            fallback_entity=str(data.get(CONF_FALLBACK_ENTITY) or DEFAULT_FALLBACK_ENTITY),
            hp_price=_as_float(data.get(CONF_HP_PRICE), DEFAULT_HP_PRICE),
            hc_price=_as_float(data.get(CONF_HC_PRICE), DEFAULT_HC_PRICE),
            ladder=Ladder(
                comfort=_as_float(data.get(CONF_COMFORT_SETPOINT), DEFAULT_COMFORT_SETPOINT),
                frost=_as_float(data.get(CONF_FROST_SETPOINT), DEFAULT_FROST_SETPOINT),
            ),
            profile=profile,
            windows=windows,
        )


@dataclass(frozen=True, slots=True)
class RoomConfig:
    """Resolved configuration for one heated room."""

    subentry_id: str
    name: str
    area_id: str | None = None
    temp_entity: str | None = None
    humidity_entity: str | None = None
    fil_pilote_entity: str | None = None
    relay_entity: str | None = None
    power_entity: str | None = None
    energy_entity: str | None = None
    nominal_power: float = DEFAULT_NOMINAL_POWER
    surface: float = 0.0
    volume: float = 0.0

    @property
    def slug(self) -> str:
        """Stable identifier used in entity unique ids."""
        return self.subentry_id

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> RoomConfig:
        data: dict[str, Any] = dict(subentry.data or {})
        return cls(
            subentry_id=subentry.subentry_id,
            name=subentry.title or data.get(CONF_ROOM_NAME, "Room"),
            area_id=data.get(CONF_ROOM_AREA) or None,
            temp_entity=data.get(CONF_ROOM_TEMP_ENTITY) or None,
            humidity_entity=data.get(CONF_ROOM_HUMIDITY_ENTITY) or None,
            fil_pilote_entity=data.get(CONF_ROOM_FIL_PILOTE_ENTITY) or None,
            relay_entity=data.get(CONF_ROOM_RELAY_ENTITY) or None,
            power_entity=data.get(CONF_ROOM_POWER_ENTITY) or None,
            energy_entity=data.get(CONF_ROOM_ENERGY_ENTITY) or None,
            nominal_power=_as_float(data.get(CONF_ROOM_NOMINAL_POWER), DEFAULT_NOMINAL_POWER),
            surface=_as_float(data.get(CONF_ROOM_SURFACE), 0.0),
            volume=_as_float(data.get(CONF_ROOM_VOLUME), 0.0),
        )


def room_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return the room subentries of ``entry``."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_ROOM
    ]
