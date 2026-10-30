"""Runtime state: rooms, sampling buffer, persistence and entity lookups."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .actuators.select_driver import SelectDriver
from .const import (
    DEGRADED_SENSOR_FROZEN,
    DEGRADED_SENSOR_MISSING,
    SAMPLE_INTERVAL,
    SENSOR_FROZEN_DELTA,
    SENSOR_FROZEN_WINDOW,
    STORAGE_KEY,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)
from .coordinator import ThermOptCoordinator
from .core.orders import Order, order_from_z2m
from .core.ring_buffer import RoomSeries
from .perception.liveness import is_frozen
from .perception.weather import WeatherProvider
from .settings import RoomConfig, SystemConfig, room_subentries

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = {"unavailable", "unknown", "none", ""}


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class RoomRuntime:
    """Live state for a single heated room."""

    def __init__(self, hass: HomeAssistant, config: RoomConfig) -> None:
        self.hass = hass
        self.config = config
        self.series = RoomSeries()
        self.enabled = True
        self.target_min: float | None = None
        self.driver = (
            SelectDriver(hass, config.fil_pilote_entity) if config.fil_pilote_entity else None
        )

    # -- live values ---------------------------------------------------------
    def _state_value(self, entity_id: str | None) -> object | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or str(state.state).lower() in UNAVAILABLE:
            return None
        return state.state

    @property
    def t_air(self) -> float | None:
        return _as_float(self._state_value(self.config.temp_entity))

    @property
    def humidity(self) -> float | None:
        return _as_float(self._state_value(self.config.humidity_entity))

    @property
    def power(self) -> float | None:
        return _as_float(self._state_value(self.config.power_entity))

    @property
    def energy(self) -> float | None:
        return _as_float(self._state_value(self.config.energy_entity))

    @property
    def order(self) -> Order | None:
        if self.driver is not None:
            return self.driver.read()
        raw = self._state_value(self.config.fil_pilote_entity)
        return order_from_z2m(str(raw)) if raw is not None else None

    # -- liveness (§ 7.1.3) --------------------------------------------------
    def update_liveness(self, now: datetime) -> set[str]:
        reasons: set[str] = set()

        if self.t_air is None:
            reasons.add(DEGRADED_SENSOR_MISSING)

        samples = self.series.tail(SENSOR_FROZEN_WINDOW, now.timestamp())
        if is_frozen(samples, window=SENSOR_FROZEN_WINDOW, delta=SENSOR_FROZEN_DELTA):
            reasons.add(DEGRADED_SENSOR_FROZEN)

        return reasons

    # -- persistence ---------------------------------------------------------
    def dump(self) -> dict:
        return {
            "enabled": self.enabled,
            "series": self.series.to_dict(),
        }

    def load(self, data: dict | None) -> None:
        if not data:
            return
        self.enabled = bool(data.get("enabled", True))
        series = data.get("series")
        if series:
            self.series = RoomSeries.from_dict(series)


class ThermOptRuntime:
    """Glue between the config entry, perception and the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = SystemConfig.from_entry(entry)
        self.rooms: dict[str, RoomRuntime] = {}
        self.last_cycle: datetime | None = None
        self.store: Store[dict] = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
        self.weather = WeatherProvider(hass, self.config.weather_entity)
        self.coordinator = ThermOptCoordinator(hass, self, entry)
        self._unsub_sampler = None

    # ------------------------------------------------------------------
    async def async_setup(self) -> None:
        stored = await self.store.async_load() or {}

        self.weather.load(stored.get("weather"))
        self._build_rooms(stored.get("rooms", {}))
        self.last_cycle = _parse(stored.get("last_cycle"))

        await self.coordinator.async_config_entry_first_refresh()

        self._unsub_sampler = async_track_time_interval(
            self.hass, self._async_sample, SAMPLE_INTERVAL
        )
        await self._async_sample()

    async def async_shutdown(self) -> None:
        if self._unsub_sampler is not None:
            self._unsub_sampler()
            self._unsub_sampler = None
        await self.store.async_save(self._dump())

    # ------------------------------------------------------------------
    def _build_rooms(self, stored: dict | None = None) -> None:
        stored = stored or {}
        rooms: dict[str, RoomRuntime] = {}
        for subentry in room_subentries(self.entry):
            room = RoomRuntime(self.hass, RoomConfig.from_subentry(subentry))
            room.load(stored.get(room.config.subentry_id))
            rooms[room.config.subentry_id] = room
        self.rooms = rooms

    async def async_reload(self) -> None:
        """Re-read configuration and rebuild rooms (options / subentry change)."""
        self.config = SystemConfig.from_entry(self.entry)
        snapshot = self._dump()
        self.weather = WeatherProvider(self.hass, self.config.weather_entity)
        self.weather.load(snapshot.get("weather"))
        self._build_rooms(snapshot.get("rooms"))
        self._schedule_save()
        await self.coordinator.async_refresh()

    @callback
    def async_set_room_enabled(self, subentry_id: str, enabled: bool) -> None:
        room = self.rooms.get(subentry_id)
        if room is None:
            return
        room.enabled = enabled
        self._schedule_save()

    # ------------------------------------------------------------------
    async def _async_sample(self, _now: datetime | None = None) -> None:
        now = dt_util.now()
        stamp = now.timestamp()
        for room in self.rooms.values():
            if not room.enabled:
                continue
            order = room.order
            room.series.append(
                stamp,
                t_air=room.t_air,
                humidity=room.humidity,
                power=room.power,
                energy=room.energy,
                order=order.value if order else None,
            )
        self._schedule_save()

    def _schedule_save(self) -> None:
        self.store.async_delay_save(self._dump, STORAGE_SAVE_DELAY)

    def _dump(self) -> dict:
        return {
            "weather": self.weather.dump(),
            "last_cycle": self.last_cycle.isoformat() if self.last_cycle else None,
            "rooms": {sid: room.dump() for sid, room in self.rooms.items()},
        }


def _parse(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    return dt_util.parse_datetime(raw)
