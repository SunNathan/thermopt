"""Guard rails: the safety layer that is allowed to write when a room is cold.

Pure Python: no Home Assistant imports. The coordinator feeds it a snapshot of
the room and applies the returned decision.

Priority is absolute and never negotiable against money:

1. frost protection (below ``ABSOLUTE_FLOOR``)  -> Confort, always
2. comfort floor (below ``T_min - GUARD_MARGIN``) -> Confort
3. open window -> no write, let the situation settle

Manual changes are not tracked here: in active mode ThermOpt is authoritative,
and observation mode is the way to take the radiator back by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .orders import Order

# Safety thresholds (§ 7.1 of the specification). They live here, not in
# ``const.py``, so this module stays importable without the package root.
ABSOLUTE_FLOOR = 7.0  # °C, frost protection
GUARD_MARGIN = 0.5  # forced Confort below T_min - GUARD_MARGIN
GUARD_HYSTERESIS = 0.3  # released above T_min - GUARD_MARGIN + HYSTERESIS
WINDOW_DROP = 1.5  # °C lost during ...
WINDOW_SECONDS = 10 * 60  # ... this window => open window
WINDOW_SUSPEND_MINUTES = 60  # let the radiator handle it
EFFECT_CHECK_MINUTES = 15
EFFECT_MIN_POWER = 5.0  # W, below this the radiator is not heating


class SafetyState(StrEnum):
    """What the safety layer is doing, exposed per room."""

    IDLE = "inactif"
    FLOOR = "plancher"
    FROST = "hors_gel"
    WINDOW = "fenetre"


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    """What to do with the radiator now."""

    order: Order | None = None
    state: SafetyState = SafetyState.IDLE
    #: True when the write may bypass the "1 change / 30 min" window.
    escalate: bool = False
    #: Whether the comfort guard should stay armed after this evaluation.
    armed: bool = False
    reason: str = ""
    suspend_until: datetime | None = None


def guard_thresholds(t_min: float) -> tuple[float, float]:
    """Return ``(arm_below, release_above)`` for the comfort guard."""
    arm = t_min - GUARD_MARGIN
    return arm, arm + GUARD_HYSTERESIS


def detect_window(samples: list[tuple[float, float | None]], now: datetime) -> bool:
    """True when the room lost more than ``WINDOW_DROP`` in ``WINDOW_SECONDS``."""
    values = [value for _ts, value in samples if value is not None]
    if len(values) < 3:
        return False
    return (max(values) - min(values)) > WINDOW_DROP


def evaluate(
    *,
    now: datetime,
    t_air: float | None,
    t_min: float,
    current: Order | None,
    armed: bool,
    suspended_until: datetime | None,
    window_open: bool,
) -> SafetyDecision:
    """Decide whether the safety layer must force an order.

    The frost guard wins over everything, including an open window: a room
    close to freezing must be heated whatever the house is doing.
    """
    if t_air is not None and t_air < ABSOLUTE_FLOOR:
        return SafetyDecision(
            order=Order.COMFORT,
            state=SafetyState.FROST,
            escalate=True,
            armed=True,
            reason=f"Température {t_air:.1f} °C sous le hors-gel absolu ({ABSOLUTE_FLOOR:.0f} °C)",
        )

    if suspended_until is not None and now < suspended_until:
        return SafetyDecision(
            state=SafetyState.WINDOW,
            armed=armed,
            reason=(
                "Fenêtre ouverte probable : pilotage suspendu jusqu'à "
                f"{suspended_until.strftime('%H:%M')}"
            ),
        )

    if window_open:
        return SafetyDecision(
            state=SafetyState.WINDOW,
            armed=armed,
            escalate=False,
            reason="Fenêtre ouverte détectée : on laisse le radiateur gérer",
            suspend_until=now + timedelta(minutes=WINDOW_SUSPEND_MINUTES),
        )

    arm_below, release_above = guard_thresholds(t_min)

    if t_air is None:
        return SafetyDecision(armed=armed, reason="Température inconnue")

    if t_air < arm_below:
        return SafetyDecision(
            order=Order.COMFORT,
            state=SafetyState.FLOOR,
            escalate=not armed,
            armed=True,
            reason=(
                f"Température {t_air:.1f} °C sous la borne de confort "
                f"({arm_below:.1f} °C) : Confort forcé"
            ),
        )

    if armed and t_air <= release_above:
        # Keep holding until the room is clearly back above the threshold.
        return SafetyDecision(
            order=Order.COMFORT,
            state=SafetyState.FLOOR,
            escalate=False,
            armed=True,
            reason=f"Retour au-dessus de la borne en cours ({t_air:.1f} °C)",
        )

    return SafetyDecision(armed=False, reason="Borne de confort respectée")


__all__ = [
    "SafetyDecision",
    "SafetyState",
    "detect_window",
    "evaluate",
    "guard_thresholds",
    "WINDOW_SECONDS",
    "WINDOW_DROP",
]
