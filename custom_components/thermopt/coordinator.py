"""15-minute supervision cycle (perception + safety pre-checks).

The optimiser is not wired yet: this cycle observes, resolves the comfort
bounds and raises degradation flags. It never applies a fil pilote order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACTUATION_IMPLEMENTED,
    ACTUATION_REASON,
    CYCLE_INTERVAL,
    DEGRADED_ACTUATOR_UNAVAILABLE,
    DEGRADED_NO_ROOM,
    DEGRADED_PROFILE_UNREACHABLE,
    DEGRADED_RELAY_OFF,
    DEGRADED_TARIFF_MISMATCH,
    DEGRADED_WEATHER,
    DOMAIN,
    MODE_DEGRADE,
    MODE_MANUEL,
    MODE_OBSERVATION,
    MODE_PILOTAGE,
    MODE_REPLI,
    STATE_COLLECTE,
    STATE_MANUAL,
)
from .core.orders import Order
from .perception.comfort import profile_issues
from .perception.tariff import is_hc, next_transition, price_at
from .perception.weather import outdoor_temperature_at

if TYPE_CHECKING:
    from .runtime import RoomRuntime, ThermOptRuntime

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = {"unavailable", "unknown", "none", ""}


@dataclass(frozen=True, slots=True)
class LastCommand:
    """Last fil pilote order ThermOpt itself wrote (``result="aucune"`` before J2)."""

    at: datetime | None = None
    room: str | None = None
    order: Order | None = None
    result: str = "aucune"
    source: str = "aucune"

    def to_dict(self) -> dict[str, object]:
        return {
            "at": self.at.isoformat() if self.at else None,
            "room": self.room,
            "order": self.order.value if self.order else None,
            "result": self.result,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> LastCommand:
        if not data:
            return cls()
        return cls(
            at=_parse_dt(data.get("at")),
            room=data.get("room") if isinstance(data.get("room"), str) else None,
            order=Order(data["order"]) if data.get("order") in {o.value for o in Order} else None,
            result=str(data.get("result") or "aucune"),
            source=str(data.get("source") or "aucune"),
        )


@dataclass(frozen=True, slots=True)
class RoomSnapshot:
    """Per-room view exposed to the entities."""

    subentry_id: str
    name: str
    t_air: float | None = None
    humidity: float | None = None
    power: float | None = None
    energy: float | None = None
    order: Order | None = None
    requested_order: Order | None = None
    order_source: str = "aucune"
    target_min: float | None = None
    target_max: float | None = None
    guard_floor: float | None = None
    slot: str | None = None
    degraded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ThermOptData:
    """Coordinator payload."""

    status: str = STATE_COLLECTE
    mode: str = MODE_OBSERVATION
    internal_state: str = STATE_COLLECTE
    actuation_enabled: bool = False
    actuation_reason: str | None = ACTUATION_REASON
    last_command: LastCommand | None = None
    last_cycle: datetime | None = None
    next_cycle: datetime | None = None
    is_hc: bool = False
    price_now: float = 0.0
    next_transition: datetime | None = None
    outdoor_now: float | None = None
    forecast_source: str = "none"
    degraded: tuple[str, ...] = ()
    rooms: dict[str, RoomSnapshot] = field(default_factory=dict)


class ThermOptCoordinator(DataUpdateCoordinator[ThermOptData]):
    """Drive the whole supervision cycle."""

    def __init__(self, hass: HomeAssistant, runtime: ThermOptRuntime, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} cycle",
            update_interval=CYCLE_INTERVAL,
        )
        self.runtime = runtime

    # ------------------------------------------------------------------
    async def _async_update_data(self) -> ThermOptData:
        runtime = self.runtime
        now = dt_util.now()
        config = runtime.config

        runtime.last_cycle = now

        forecast = await runtime.weather.async_snapshot(now)
        degraded: set[str] = set()
        if not forecast.available or forecast.source == "synthetic":
            degraded.add(DEGRADED_WEATHER)

        if not runtime.rooms:
            degraded.add(DEGRADED_NO_ROOM)

        if profile_issues(config.profile, config.ladder, config.ladder.setpoint(Order.ECO)):
            degraded.add(DEGRADED_PROFILE_UNREACHABLE)

        hc_now = is_hc(now, list(config.windows))
        if config.hc_binary_entity:
            state = self.hass.states.get(config.hc_binary_entity)
            if state is not None and str(state.state).lower() not in UNAVAILABLE:
                actual = str(state.state).lower() == "on"
                if actual != hc_now:
                    _LOGGER.info(
                        "Tariff mismatch: schedule says %s, %s says %s",
                        "HC" if hc_now else "HP",
                        config.hc_binary_entity,
                        state.state,
                    )
                    degraded.add(DEGRADED_TARIFF_MISMATCH)

        present = self._presence()
        rooms: dict[str, RoomSnapshot] = {}
        for room in runtime.rooms.values():
            rooms[room.config.subentry_id] = await self._async_room_snapshot(
                room, now, present=present
            )
            degraded.update(rooms[room.config.subentry_id].degraded)

        auto = self._auto_enabled()
        internal_state = self._status(degraded)
        last_command = runtime.last_command
        actuation_enabled = ACTUATION_IMPLEMENTED and auto and not degraded

        return ThermOptData(
            status=internal_state,
            mode=self._mode(auto=auto, degraded=degraded),
            internal_state=internal_state,
            actuation_enabled=actuation_enabled,
            actuation_reason=None if actuation_enabled else self._actuation_reason(auto, degraded),
            last_command=last_command,
            last_cycle=now,
            next_cycle=now + CYCLE_INTERVAL,
            is_hc=hc_now,
            price_now=price_at(now, list(config.windows), config.hp_price, config.hc_price),
            next_transition=next_transition(now, list(config.windows)),
            outdoor_now=outdoor_temperature_at(forecast, now),
            forecast_source=forecast.source,
            degraded=tuple(sorted(degraded)),
            rooms=rooms,
        )

    # ------------------------------------------------------------------
    async def _async_room_snapshot(
        self, room: RoomRuntime, now: datetime, *, present: bool
    ) -> RoomSnapshot:
        config = self.runtime.config
        t_min = config.profile.t_min(now, present=present)
        _, t_max = config.profile.band(now, present=present)
        guard = config.profile.guard_floor(now, present=present)

        reasons = room.update_liveness(now)
        room.target_min = t_min

        if room.driver is None or not room.driver.available:
            reasons.add(DEGRADED_ACTUATOR_UNAVAILABLE)

        if room.config.relay_entity:
            relay = self.hass.states.get(room.config.relay_entity)
            if relay is not None and str(relay.state).lower() == "off":
                reasons.add(DEGRADED_RELAY_OFF)
                await self._async_restore_relay(room)

        return RoomSnapshot(
            subentry_id=room.config.subentry_id,
            name=room.config.name,
            t_air=room.t_air,
            humidity=room.humidity,
            power=room.power,
            energy=room.energy,
            order=room.order,
            requested_order=self._requested_order(room),
            order_source=self._order_source(room, now),
            target_min=round(t_min, 2),
            target_max=round(t_max, 2),
            guard_floor=guard,
            slot=config.profile.slot_at(now),
            degraded=tuple(sorted(reasons)),
        )

    async def _async_restore_relay(self, room: RoomRuntime) -> None:
        """Safety: a relay left open silently disables the heater (§ 7.1)."""
        if room.driver is None or room.config.relay_entity is None:
            return
        if not room.enabled or not self._auto_enabled():
            return

        _LOGGER.warning(
            "Relay %s is off while room '%s' should be heated: restoring",
            room.config.relay_entity,
            room.config.name,
        )
        try:
            await self.hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": room.config.relay_entity},
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001 - never break the cycle on this
            _LOGGER.error("Could not restore relay %s: %s", room.config.relay_entity, err)
        self._notify_once(
            f"thermopt_relay_{room.config.subentry_id}",
            "ThermOpt - relais coupé",
            f"Le relais du module fil pilote de « {room.config.name} » était coupé. "
            "ThermOpt l'a remis en marche.",
        )

    # ------------------------------------------------------------------
    def _presence(self) -> bool:
        entity_id = self.runtime.config.presence_entity
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None and str(state.state).lower() == "on"

    def _auto_enabled(self) -> bool:
        entity_id = self.runtime.config.auto_entity
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        return state is not None and str(state.state).lower() == "on"

    def _status(self, degraded: set[str]) -> str:
        if not self._auto_enabled():
            return STATE_MANUAL
        return STATE_COLLECTE

    def _mode(self, *, auto: bool, degraded: set[str]) -> str:
        """Readable mode shown by ``sensor.thermopt_statut``."""
        if not auto:
            return MODE_MANUEL
        if self.runtime.fallback_active:
            return MODE_REPLI
        if not ACTUATION_IMPLEMENTED:
            return MODE_OBSERVATION
        if degraded:
            return MODE_DEGRADE
        return MODE_PILOTAGE

    def _actuation_reason(self, auto: bool, degraded: set[str]) -> str:
        """Why no order is being written, in plain language."""
        if not auto:
            return "Mode manuel : ThermOpt n'écrit aucun ordre"
        if self.runtime.fallback_active:
            return "Repli actif : le planning natif pilote le chauffage"
        if not ACTUATION_IMPLEMENTED:
            return ACTUATION_REASON
        if degraded:
            return f"Situation dégradée : {', '.join(sorted(degraded))}"
        return "Pilotage actif"

    def _requested_order(self, room: RoomRuntime) -> Order | None:
        """Order ThermOpt wants, as opposed to what the module actually holds."""
        last = self.runtime.last_command
        if last is None or last.room != room.config.subentry_id:
            return None
        return last.order

    def _order_source(self, room: RoomRuntime, now: datetime) -> str:
        """Who last changed the module: ThermOpt, a human, or the fallback."""
        if self.runtime.fallback_active:
            return "repli"

        last = self.runtime.last_command
        if (
            last is not None
            and last.room == room.config.subentry_id
            and last.at is not None
            and (now - last.at).total_seconds() < 600
        ):
            return "thermopt"

        if room.driver is None or not room.driver.available:
            return "inconnue"

        if room.order is None:
            return "inconnue"

        return "manuel"

    def _notify_once(self, notification_id: str, title: str, message: str) -> None:
        from homeassistant.components import persistent_notification

        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=notification_id
        )


def _parse_dt(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    return dt_util.parse_datetime(raw)
