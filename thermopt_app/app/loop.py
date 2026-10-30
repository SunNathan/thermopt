"""The 15-minute supervision loop.

Milestone B: perception and safety. No model, no optimiser — the loop reads the
sensors, evaluates the guard rails and writes a fil pilote order only when the
safety layer demands it (and never in observation mode).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo

from thermopt_lib.core.orders import Order, order_from_z2m, z2m_value
from thermopt_lib.core.ring_buffer import RoomSeries
from thermopt_lib.core.safety import (
    EFFECT_CHECK_MINUTES,
    EFFECT_MIN_POWER,
    MANUAL_WRITE_GRACE,
    WINDOW_SECONDS,
    SafetyDecision,
    SafetyState,
    detect_window,
    evaluate,
    manual_hold,
)
from thermopt_lib.perception.comfort import ComfortProfile
from thermopt_lib.perception.liveness import is_frozen
from thermopt_lib.perception.tariff import is_hc, parse_windows, price_at
from thermopt_lib.reporting import describe_reason

from .config import AppConfig, RoomConfig
from .ha import HaClient
from .publish import Publisher, RoomState, Snapshot

_LOGGER = logging.getLogger(__name__)

CYCLE_SECONDS = 15 * 60
FROZEN_WINDOW = 45 * 60
FROZEN_DELTA = 0.05
FORECAST_TTL = timedelta(hours=1)
MIN_DELAY = 30.0


@dataclass(slots=True)
class RoomRuntime:
    """Per-room state that must survive between cycles."""

    config: RoomConfig
    series: RoomSeries = field(default_factory=RoomSeries)
    guard_armed: bool = False
    manual_hold_until: datetime | None = None
    suspended_until: datetime | None = None
    last_written: Order | None = None
    last_write_at: datetime | None = None
    pending_check: datetime | None = None
    no_effect: bool = False
    safety: SafetyState = SafetyState.IDLE
    safety_reason: str = ""
    target_min: float | None = None

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name


class SupervisionLoop:
    """Compute, decide, and write when allowed."""

    def __init__(
        self,
        ha: HaClient,
        publisher: Publisher,
        config: AppConfig,
        timezone: tzinfo,
    ) -> None:
        self._ha = ha
        self._publisher = publisher
        self._config = config
        self._tz = timezone
        self._rooms: dict[str, RoomRuntime] = {
            room.id: RoomRuntime(config=room) for room in config.rooms
        }
        self._forecast: list[tuple[float, float]] = []
        self._forecast_at: datetime | None = None
        self.degraded: list[str] = []
        self.last_cycle: datetime | None = None
        self.mode = "observation"

    # -- configuration -------------------------------------------------------
    def apply_config(self, config: AppConfig) -> None:
        """Reload the rooms after the user saves the configuration page."""
        self._config = config
        rooms: dict[str, RoomRuntime] = {}
        for room in config.rooms:
            runtime = self._rooms.get(room.id) or RoomRuntime(config=room)
            runtime.config = room
            rooms[room.id] = runtime
        self._rooms = rooms
        _LOGGER.info("Configuration rechargée : %s pièce(s)", len(rooms))

    @property
    def rooms(self) -> dict[str, RoomRuntime]:
        return self._rooms

    # -- main loop -----------------------------------------------------------
    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.cycle()
            except Exception:  # noqa: BLE001 - a bad cycle must not kill the loop
                _LOGGER.exception("Cycle en échec")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._seconds_until_next_cycle())
            except TimeoutError:
                continue

    def _seconds_until_next_cycle(self) -> float:
        now = datetime.now(self._tz).timestamp()
        next_tick = (now // CYCLE_SECONDS + 1) * CYCLE_SECONDS
        return max(MIN_DELAY, next_tick - now)

    # -- one cycle -----------------------------------------------------------
    async def cycle(self) -> None:
        now = datetime.now(self._tz)
        config = self._config
        await self._ha.refresh_states()

        self.degraded = []
        self.last_cycle = now

        windows = parse_windows(config.hc_windows)
        price = price_at(now, windows, config.hp_price, config.hc_price)
        in_hc = is_hc(now, windows)
        profile = config.profile

        await self._refresh_forecast(now)

        auto_ok = await self._ha.is_on(config.auto_entity) if config.auto_entity else True
        fallback = await self._fallback_active()
        active = config.active and auto_ok and not fallback
        self.mode = self._mode(config, active)

        room_states = [
            await self._process_room(room, now, profile, active) for room in self._rooms.values()
        ]

        await self._publisher.publish_state(
            Snapshot(
                mode=self.mode,
                degraded=bool(self.degraded),
                details=list(self.degraded),
                price=price,
                last_cycle=now.isoformat(timespec="seconds"),
                rooms=room_states,
            )
        )
        _LOGGER.info(
            "Cycle %s %.4f €/kWh, mode %s : %s",
            "HC" if in_hc else "HP",
            price,
            self.mode,
            ", ".join(f"{r.name}={r.safety.value}" for r in self._rooms.values()),
        )

    def _mode(self, config: AppConfig, active: bool) -> str:
        if not config.active:
            return "observation"
        return "actif" if active else "repli"

    # -- per room ------------------------------------------------------------
    async def _process_room(
        self,
        room: RoomRuntime,
        now: datetime,
        profile: ComfortProfile,
        active: bool,
    ) -> RoomState:
        t_air = await self._ha.numeric(room.config.temp_entity)
        power = await self._ha.numeric(room.config.power_entity)
        current = self._current_order(room)

        room.series.append(now.timestamp(), t_air=t_air, power=power)

        if t_air is None:
            self.degraded.append(f"{room.name} : capteur de température absent")

        samples = room.series.tail(FROZEN_WINDOW, now.timestamp())
        if is_frozen(samples, window=FROZEN_WINDOW, delta=FROZEN_DELTA):
            self.degraded.append(f"{room.name} : capteur figé")

        self._detect_manual(room, current, now)

        t_min = profile.t_min(now, present=False)
        decision = evaluate(
            now=now,
            t_air=t_air,
            t_min=t_min,
            current=current,
            armed=room.guard_armed,
            suspended_until=room.suspended_until,
            manual_hold_until=room.manual_hold_until,
            window_open=detect_window(room.series.tail(WINDOW_SECONDS, now.timestamp()), now),
        )
        if decision.suspend_until is not None:
            room.suspended_until = decision.suspend_until
        room.guard_armed = decision.armed
        room.safety = decision.state
        room.safety_reason = decision.reason
        room.target_min = round(t_min, 1)

        if active:
            await self._apply(room, decision, now)
        else:
            _LOGGER.info(
                "Observation — %s : %s (%s)",
                room.name,
                decision.order.value if decision.order else "aucun ordre",
                decision.reason,
            )

        self._check_effect(room, now, t_air, power)

        return RoomState(
            id=room.id,
            name=room.name,
            temperature=t_air,
            target_min=round(t_min, 1),
            safety=decision.state.value,
            safety_reason=decision.reason,
            applied_order=current,
            order_source="thermopt" if room.last_written is current else "manuel",
            power=power,
        )

    def _current_order(self, room: RoomRuntime) -> Order | None:
        entity = room.config.fil_pilote_entity
        if not entity:
            return None
        state = self._ha.cached().get(entity)
        if state is None or not state.available:
            return None
        return order_from_z2m(state.state)

    def _detect_manual(self, room: RoomRuntime, current: Order | None, now: datetime) -> None:
        if room.last_written is None or room.manual_hold_until is not None:
            return
        if current is None or current is room.last_written:
            return
        if (
            room.last_write_at is not None
            and (now - room.last_write_at).total_seconds() < MANUAL_WRITE_GRACE
        ):
            return
        room.manual_hold_until = manual_hold(now)
        _LOGGER.info("%s : réglage manuel détecté, pièce gelée 2 h", room.name)

    async def _apply(self, room: RoomRuntime, decision: SafetyDecision, now: datetime) -> None:
        order = decision.order
        if order is None or not room.config.fil_pilote_entity:
            return

        if self._current_order(room) is order:
            return

        if decision.escalate:
            # Escalation may bypass the 30-minute window, never the 5-minute
            # dwell time the module needs to decode the order.
            if room.last_write_at is not None and (now - room.last_write_at).total_seconds() < 60:
                return
        elif not self._rate_ok(room, now):
            return

        try:
            await self._ha.select_option(room.config.fil_pilote_entity, z2m_value(order))
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Écriture refusée sur %s : %s", room.name, err)
            self.degraded.append(f"{room.name} : écriture refusée")
            return

        room.last_written = order
        room.last_write_at = now
        room.pending_check = now + timedelta(minutes=EFFECT_CHECK_MINUTES)
        _LOGGER.info("Sécurité appliquée sur %s : %s (%s)", room.name, order.value, decision.reason)

    @staticmethod
    def _rate_ok(room: RoomRuntime, now: datetime) -> bool:
        if room.last_write_at is None:
            return True
        return (now - room.last_write_at).total_seconds() >= 30 * 60

    def _check_effect(
        self, room: RoomRuntime, now: datetime, t_air: float | None, power: float | None
    ) -> None:
        if room.pending_check is None or now < room.pending_check:
            return
        room.pending_check = None
        if room.last_written is None or power is None or t_air is None:
            return

        setpoint = self._config.ladder.setpoint(room.last_written)
        missing = power <= EFFECT_MIN_POWER and t_air < setpoint - 0.5
        if missing and not room.no_effect:
            _LOGGER.warning(
                "%s : aucun effet mesuré (%.0f W, %.1f °C pour une consigne de %.1f °C)",
                room.name,
                power,
                t_air,
                setpoint,
            )
            self.degraded.append(f"{room.name} : ordre sans effet mesuré")
        room.no_effect = missing

    # -- helpers -------------------------------------------------------------
    async def _fallback_active(self) -> bool:
        entity = self._config.fallback_entity
        if not entity:
            return False
        state = self._ha.cached().get(entity)
        return state is not None and state.state.lower() == "on"

    async def _refresh_forecast(self, now: datetime) -> None:
        entity = self._config.weather_entity
        if not entity:
            return
        if self._forecast and self._forecast_at and now - self._forecast_at < FORECAST_TTL:
            return
        try:
            self._forecast = await self._ha.hourly_forecast(entity)
            self._forecast_at = now
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Météo indisponible : %s", err)
            self.degraded.append(
                "météo indisponible : dernière valeur conservée"
                if self._forecast
                else "météo indisponible"
            )

    @property
    def forecast(self) -> list[tuple[float, float]]:
        return self._forecast

    def decision_text(self, room_id: str) -> str:
        room = self._rooms.get(room_id)
        if room is None:
            return ""
        if room.safety is SafetyState.IDLE:
            return "Borne de confort respectée"
        return room.safety_reason or describe_reason(room.safety.value)
