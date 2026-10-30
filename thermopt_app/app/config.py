"""Application configuration: model, validation and serialisation.

Pure Python, but it depends on the shared library (``thermopt_lib``) for the
order ladder, the tariff parser and the comfort profile — the exact same code
the integration used, so the messages are identical.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from thermopt_lib.core.orders import Ladder, Order
from thermopt_lib.perception.comfort import (
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
    profile_issues,
)
from thermopt_lib.perception.tariff import InvalidWindow, parse_windows

DEFAULT_HP_PRICE = 0.2065
DEFAULT_HC_PRICE = 0.1579
DEFAULT_HC_WINDOWS = "22:00-06:00, 12:00-14:00"
DEFAULT_COMFORT_SETPOINT = 20.5
DEFAULT_FROST_SETPOINT = 7.0
DEFAULT_FALLBACK_ENTITY = "input_boolean.thermopt_repli"

SLOTS = (SLOT_NIGHT, SLOT_MORNING, SLOT_DAY, SLOT_EVENING)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    """Empty, missing or invalid means "derive it"."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class RoomConfig:
    """One heated room."""

    id: str
    name: str
    temp_entity: str | None = None
    humidity_entity: str | None = None
    fil_pilote_entity: str | None = None
    relay_entity: str | None = None
    power_entity: str | None = None
    energy_entity: str | None = None

    @staticmethod
    def new() -> RoomConfig:
        return RoomConfig(id=uuid.uuid4().hex[:8], name="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "temp_entity": self.temp_entity,
            "humidity_entity": self.humidity_entity,
            "fil_pilote_entity": self.fil_pilote_entity,
            "relay_entity": self.relay_entity,
            "power_entity": self.power_entity,
            "energy_entity": self.energy_entity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoomConfig:
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            name=str(data.get("name") or ""),
            temp_entity=data.get("temp_entity") or None,
            humidity_entity=data.get("humidity_entity") or None,
            fil_pilote_entity=data.get("fil_pilote_entity") or None,
            relay_entity=data.get("relay_entity") or None,
            power_entity=data.get("power_entity") or None,
            energy_entity=data.get("energy_entity") or None,
        )


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Whole application configuration, persisted in ``/data/config.json``."""

    rooms: tuple[RoomConfig, ...] = ()
    weather_entity: str | None = None
    auto_entity: str | None = None
    fallback_entity: str = DEFAULT_FALLBACK_ENTITY
    hp_price: float = DEFAULT_HP_PRICE
    hc_price: float = DEFAULT_HC_PRICE
    hc_windows: str = DEFAULT_HC_WINDOWS
    comfort_setpoint: float = DEFAULT_COMFORT_SETPOINT
    frost_setpoint: float = DEFAULT_FROST_SETPOINT
    eco_setpoint: float | None = None
    active: bool = True
    starts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_STARTS))
    weekday: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEEKDAY))
    weekend: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEEKEND))
    present_day: float = DEFAULT_PRESENT_DAY
    tolerance: float = DEFAULT_TOLERANCE
    high_margin: float = DEFAULT_HIGH_MARGIN
    supervisor_ack: bool = False
    optimizer_active: bool = False

    # -- derived -------------------------------------------------------------
    @property
    def ladder(self) -> Ladder:
        return Ladder(
            comfort=self.comfort_setpoint,
            frost=self.frost_setpoint,
            eco=self.eco_setpoint,
        )

    @property
    def profile(self) -> ComfortProfile:
        return ComfortProfile.from_config(
            starts=self.starts,
            weekday=self.weekday,
            weekend=self.weekend,
            present_day=self.present_day,
            tolerance=self.tolerance,
            high_margin=self.high_margin,
        )

    def room(self, room_id: str) -> RoomConfig | None:
        for room in self.rooms:
            if room.id == room_id:
                return room
        return None

    def with_room(self, room: RoomConfig) -> AppConfig:
        rooms = tuple(room if existing.id == room.id else existing for existing in self.rooms)
        if not any(existing.id == room.id for existing in self.rooms):
            rooms = (*self.rooms, room)
        return replace(self, rooms=rooms)

    def without_room(self, room_id: str) -> AppConfig:
        return replace(self, rooms=tuple(r for r in self.rooms if r.id != room_id))

    # -- serialisation -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "rooms": [room.to_dict() for room in self.rooms],
            "weather_entity": self.weather_entity,
            "auto_entity": self.auto_entity,
            "fallback_entity": self.fallback_entity,
            "hp_price": self.hp_price,
            "hc_price": self.hc_price,
            "hc_windows": self.hc_windows,
            "comfort_setpoint": self.comfort_setpoint,
            "frost_setpoint": self.frost_setpoint,
            "eco_setpoint": self.eco_setpoint,
            "active": self.active,
            "starts": self.starts,
            "weekday": self.weekday,
            "weekend": self.weekend,
            "present_day": self.present_day,
            "tolerance": self.tolerance,
            "high_margin": self.high_margin,
            "supervisor_ack": self.supervisor_ack,
            "optimizer_active": self.optimizer_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AppConfig:
        data = data or {}
        rooms = tuple(
            RoomConfig.from_dict(item) for item in data.get("rooms", []) if isinstance(item, dict)
        )
        return cls(
            rooms=rooms,
            weather_entity=data.get("weather_entity") or None,
            auto_entity=data.get("auto_entity") or None,
            fallback_entity=str(data.get("fallback_entity") or DEFAULT_FALLBACK_ENTITY),
            hp_price=_as_float(data.get("hp_price"), DEFAULT_HP_PRICE),
            hc_price=_as_float(data.get("hc_price"), DEFAULT_HC_PRICE),
            hc_windows=str(data.get("hc_windows") or DEFAULT_HC_WINDOWS),
            comfort_setpoint=_as_float(data.get("comfort_setpoint"), DEFAULT_COMFORT_SETPOINT),
            frost_setpoint=_as_float(data.get("frost_setpoint"), DEFAULT_FROST_SETPOINT),
            eco_setpoint=_optional_float(data.get("eco_setpoint")),
            active=bool(data.get("active", True)),
            starts={**DEFAULT_STARTS, **(data.get("starts") or {})},
            weekday={**DEFAULT_WEEKDAY, **(data.get("weekday") or {})},
            weekend={**DEFAULT_WEEKEND, **(data.get("weekend") or {})},
            present_day=_as_float(data.get("present_day"), DEFAULT_PRESENT_DAY),
            tolerance=_as_float(data.get("tolerance"), DEFAULT_TOLERANCE),
            high_margin=_as_float(data.get("high_margin"), DEFAULT_HIGH_MARGIN),
            supervisor_ack=bool(data.get("supervisor_ack", False)),
            optimizer_active=bool(data.get("optimizer_active", False)),
        )


def validate(config: AppConfig) -> list[str]:
    """Return human-readable errors; an empty list means the config is usable."""
    errors: list[str] = []

    if not config.rooms:
        errors.append("Aucune pièce configurée : ajoute au moins une pièce.")

    for room in config.rooms:
        label = room.name.strip() or "(pièce sans nom)"
        if not room.name.strip():
            errors.append("Chaque pièce doit avoir un nom.")
        if not room.fil_pilote_entity:
            errors.append(f"{label} : l'entité fil pilote (select) est obligatoire.")
        if not room.temp_entity:
            errors.append(f"{label} : le capteur de température est obligatoire.")

    seen: set[str] = set()
    for room in config.rooms:
        if room.id in seen:
            errors.append(f"Identifiant de pièce dupliqué : {room.id}")
        seen.add(room.id)

    try:
        parse_windows(config.hc_windows)
    except InvalidWindow:
        errors.append("Plages Heures Creuses invalides : format attendu 22:00-06:00, 12:00-14:00.")

    if config.frost_setpoint >= config.comfort_setpoint - 5:
        errors.append("La consigne Hors-gel doit être au moins 5 °C sous la consigne Confort.")

    if not 5 <= config.frost_setpoint <= 12:
        errors.append("La consigne Hors-gel doit être comprise entre 5 et 12 °C.")
    if not 15 <= config.comfort_setpoint <= 25:
        errors.append("La consigne Confort doit être comprise entre 15 et 25 °C.")
    if config.eco_setpoint is not None and not (
        config.frost_setpoint < config.eco_setpoint < config.comfort_setpoint
    ):
        errors.append(
            "La consigne Eco doit être strictement comprise entre le Hors-gel "
            "et la consigne Confort."
        )
    if config.hp_price <= 0 or config.hc_price <= 0:
        errors.append("Les prix doivent être strictement positifs.")

    try:
        ladder = config.ladder
        profile = config.profile
    except (InvalidWindow, ValueError) as err:
        errors.append(f"Profil de confort invalide : {err}")
        return errors

    for issue in profile_issues(profile, ladder, ladder.setpoint(Order.ECO)):
        errors.append(describe_profile_issue(issue, ladder))

    return errors


def describe_profile_issue(issue: str, ladder: Ladder) -> str:
    """French explanation for a ladder/profile mismatch (shared with the UI)."""
    from thermopt_lib.reporting import describe_profile_issue as describe

    return describe(issue, ladder)


def profile_summary(config: AppConfig) -> list[tuple[str, float, float]]:
    """``(slot, weekday, weekend)`` rows for the configuration page."""
    profile = config.profile
    return [(slot, profile.weekday[slot], profile.weekend[slot]) for slot in SLOTS]


def ladder_rows(config: AppConfig) -> list[tuple[str, float]]:
    """``(label, setpoint)`` rows, warmest first, for the UI."""
    from thermopt_lib.core.orders import LABELS_FR

    return [(LABELS_FR[order], value) for order, value in config.ladder.setpoints().items()]
