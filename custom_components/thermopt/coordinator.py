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
    CYCLE_INTERVAL,
    DEGRADED_ACTUATOR_UNAVAILABLE,
    DEGRADED_NO_EFFECT,
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
    MODE_SECURITE,
    OBSERVATION_REASON,
    OPTIMIZER_ACTUATION,
    SAFETY_ACTUATION,
    SAFETY_REASON,
    STATE_COLLECTE,
    STATE_MANUAL,
)
from .core.orders import Order
from .core.safety import (
    EFFECT_MIN_POWER,
    WINDOW_SECONDS,
    SafetyState,
    detect_window,
    evaluate,
)
from .perception.comfort import profile_issues
from .perception.tariff import is_hc, next_transition, price_at
from .perception.weather import outdoor_temperature_at
from .reporting import describe_reason

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
    safety_state: str = "inactif"
    safety_reason: str = ""
    degraded: tuple[str, ...] = ()
    degraded_detail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ThermOptData:
    """Coordinator payload."""

    status: str = STATE_COLLECTE
    mode: str = MODE_OBSERVATION
    internal_state: str = STATE_COLLECTE
    actuation_enabled: bool = False
    actuation_reason: str | None = SAFETY_REASON
    portee: str = "aucune"
    last_command: LastCommand | None = None
    last_cycle: datetime | None = None
    next_cycle: datetime | None = None
    is_hc: bool = False
    price_now: float = 0.0
    next_transition: datetime | None = None
    outdoor_now: float | None = None
    forecast_source: str = "none"
    degraded: tuple[str, ...] = ()
    degraded_detail: tuple[str, ...] = ()
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

        issues = profile_issues(config.profile, config.ladder, config.ladder.setpoint(Order.ECO))
        if issues:
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
        actuation_enabled = (SAFETY_ACTUATION or OPTIMIZER_ACTUATION) and auto
        actuation_enabled = actuation_enabled and not runtime.fallback_active

        return ThermOptData(
            status=internal_state,
            mode=self._mode(auto=auto, degraded=degraded),
            internal_state=internal_state,
            actuation_enabled=actuation_enabled,
            actuation_reason=self._actuation_reason(auto, degraded),
            portee=self._portee(),
            last_command=last_command,
            last_cycle=now,
            next_cycle=now + CYCLE_INTERVAL,
            is_hc=hc_now,
            price_now=price_at(now, list(config.windows), config.hp_price, config.hc_price),
            next_transition=next_transition(now, list(config.windows)),
            outdoor_now=outdoor_temperature_at(forecast, now),
            forecast_source=forecast.source,
            degraded=tuple(sorted(degraded)),
            degraded_detail=tuple(self._degradation_details(degraded, issues)),
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
        else:
            room.update_manual_override(now)

        if room.config.relay_entity:
            relay = self.hass.states.get(room.config.relay_entity)
            if relay is not None and str(relay.state).lower() == "off":
                reasons.add(DEGRADED_RELAY_OFF)
                await self._async_restore_relay(room)

        decision = evaluate(
            now=now,
            t_air=room.t_air,
            t_min=t_min,
            current=room.order,
            armed=room.guard_armed,
            suspended_until=room.suspended_until,
            manual_hold_until=room.manual_hold_until,
            window_open=detect_window(room.series.tail(WINDOW_SECONDS, now.timestamp()), now),
        )
        if decision.suspend_until is not None:
            room.suspended_until = decision.suspend_until
        room.guard_armed = decision.armed

        await self._async_apply_safety(room, decision, now)

        self._refresh_effect_check(room, now)
        if room.no_effect:
            reasons.add(DEGRADED_NO_EFFECT)

        previous = room.safety_state
        room.safety_state = decision.state.value
        self._notify_safety(room, decision, previous)

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
            safety_state=decision.state.value,
            safety_reason=decision.reason,
            degraded=tuple(sorted(reasons)),
            degraded_detail=tuple(
                describe_reason(reason, room=room.config.name) for reason in sorted(reasons)
            ),
        )

    # ------------------------------------------------------------------
    async def _async_apply_safety(self, room: RoomRuntime, decision, now: datetime) -> None:
        """Write the forced order, if every gate is open."""
        if decision.order is None or room.driver is None:
            return
        if not room.enabled or not self._auto_enabled():
            return
        if self.runtime.fallback_active or not room.driver.available:
            return

        current = room.order
        if current is decision.order:
            return

        verdict = room.driver.limiter.check(now, current, decision.order)
        if not verdict.allowed:
            # The 5-minute dwell time is a hardware constraint, never bypassed.
            if verdict.reason == "dwell_time":
                return
            if not decision.escalate:
                return

        try:
            await room.driver.async_write(decision.order)
        except Exception as err:  # noqa: BLE001 - a failed write must not break the cycle
            _LOGGER.error(
                "Could not apply %s to %s: %s", decision.order.value, room.config.name, err
            )
            self.runtime.async_record_command(room.config.subentry_id, decision.order, "refusee")
            return

        self.runtime.async_record_command(room.config.subentry_id, decision.order, "envoyee")
        _LOGGER.info(
            "Safety applied %s to %s (%s)",
            decision.order.value,
            room.config.name,
            decision.reason,
        )

    def _refresh_effect_check(self, room: RoomRuntime, now: datetime) -> None:
        """Verify that a heating order actually draws power."""
        if room.pending_check is None or now < room.pending_check:
            return
        room.pending_check = None

        order = room.last_written
        power = room.power
        t_air = room.t_air
        if order is None or power is None or t_air is None:
            return

        setpoint = self.runtime.config.ladder.setpoint(order)
        missing = power <= EFFECT_MIN_POWER and t_air < setpoint - 0.5
        if missing and not room.no_effect:
            _LOGGER.warning(
                "No effect in %s: order %s, %.0f W measured, %.1f °C for a %.1f °C setpoint",
                room.config.name,
                order.value,
                power,
                t_air,
                setpoint,
            )
            self._notify_once(
                f"thermopt_effect_{room.config.subentry_id}",
                "ThermOpt - aucune puissance mesurée",
                f"« {room.config.name} » : l'ordre {order.value} est appliqué mais le "
                f"radiateur ne consomme rien ({power:.0f} W) alors que la pièce est à "
                f"{t_air:.1f} °C pour une consigne de {setpoint:.1f} °C.",
            )
        room.no_effect = missing

    def _notify_safety(self, room: RoomRuntime, decision, previous: str) -> None:
        """Notify on transitions only, so the guard cannot spam."""
        from homeassistant.components import persistent_notification

        state = decision.state.value
        notification_id = f"thermopt_safety_{room.config.subentry_id}"

        if state == SafetyState.FROST.value:
            self._notify_once(
                notification_id,
                "ThermOpt - hors-gel absolu",
                f"« {room.config.name} » : {decision.reason}. Confort forcé.",
            )
            return

        if state == SafetyState.FLOOR.value and previous != SafetyState.FLOOR.value:
            self._notify_once(
                notification_id,
                "ThermOpt - plancher de confort",
                f"« {room.config.name} » : {decision.reason}.",
            )
            return

        if state == SafetyState.IDLE.value and previous in (
            SafetyState.FLOOR.value,
            SafetyState.FROST.value,
        ):
            persistent_notification.async_dismiss(self.hass, notification_id=notification_id)

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
        if OPTIMIZER_ACTUATION and not degraded:
            return MODE_PILOTAGE
        if OPTIMIZER_ACTUATION:
            return MODE_DEGRADE
        if SAFETY_ACTUATION:
            return MODE_SECURITE
        return MODE_OBSERVATION

    def _portee(self) -> str:
        if OPTIMIZER_ACTUATION:
            return "optimiseur"
        if SAFETY_ACTUATION:
            return "securite"
        return "aucune"

    def _actuation_reason(self, auto: bool, degraded: set[str]) -> str:
        """Why no order is being written, in plain language."""
        if not auto:
            return "Mode manuel : ThermOpt n'écrit aucun ordre"
        if self.runtime.fallback_active:
            return "Repli actif : le planning natif pilote le chauffage"
        if not SAFETY_ACTUATION and not OPTIMIZER_ACTUATION:
            return OBSERVATION_REASON
        if OPTIMIZER_ACTUATION and degraded:
            return f"Situation dégradée : {', '.join(sorted(degraded))}"
        if OPTIMIZER_ACTUATION:
            return "Pilotage actif"
        return SAFETY_REASON

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

    def _degradation_details(self, reasons: set[str], issues: list[str]) -> list[str]:
        """French sentences, in order, for the global degradation flags."""
        details: list[str] = []
        for reason in sorted(reasons):
            if reason == DEGRADED_PROFILE_UNREACHABLE:
                ladder = self.runtime.config.ladder
                if issues:
                    details.extend(
                        describe_reason(reason, ladder=ladder, issue=issue) for issue in issues
                    )
                else:
                    details.append(describe_reason(reason, ladder=ladder))
            else:
                details.append(describe_reason(reason))
        return details


def _parse_dt(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    return dt_util.parse_datetime(raw)
