"""Core data model for ThermOpt: fil pilote orders and the derived setpoint ladder.

This module is **pure Python** and must never import Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Fil pilote offsets, imposed by the protocol (not configurable on the heater).
Z2M_VALUES: dict[str, str] = {
    "comfort": "comfort",
    "comfort_1": "comfort_-1",
    "comfort_2": "comfort_-2",
    "eco": "eco",
    "frost": "frost_protection",
}


class Order(StrEnum):
    """The five fil pilote orders ThermOpt is allowed to emit.

    ``off`` is deliberately absent: it is not a fil pilote order but a hard
    cut-off, and would silently stop the heater (see safety requirements).
    """

    COMFORT = "comfort"
    COMFORT_1 = "comfort_1"
    COMFORT_2 = "comfort_2"
    ECO = "eco"
    FROST = "frost"


OFFSETS: dict[Order, float] = {
    Order.COMFORT: 0.0,
    Order.COMFORT_1: -1.0,
    Order.COMFORT_2: -2.0,
    Order.ECO: -3.5,
}

LABELS_FR: dict[Order, str] = {
    Order.COMFORT: "Confort",
    Order.COMFORT_1: "Confort -1",
    Order.COMFORT_2: "Confort -2",
    Order.ECO: "Eco",
    Order.FROST: "Hors-gel",
}

# Higher rank = warmer.
RANK: dict[Order, int] = {
    Order.FROST: 0,
    Order.ECO: 1,
    Order.COMFORT_2: 2,
    Order.COMFORT_1: 3,
    Order.COMFORT: 4,
}

# Orders usable by the optimiser (frost protection is a guard rail only).
ACTIVE_ORDERS: tuple[Order, ...] = (
    Order.ECO,
    Order.COMFORT_2,
    Order.COMFORT_1,
    Order.COMFORT,
)

Z2M_TO_ORDER: dict[str, Order] = {Z2M_VALUES[o.value]: o for o in Order}


def z2m_value(order: Order) -> str:
    """Return the Zigbee2MQTT ``pilot_wire_mode`` value for ``order``."""
    return Z2M_VALUES[order.value]


def order_from_z2m(value: str | None) -> Order | None:
    """Parse a Zigbee2MQTT ``pilot_wire_mode`` value.

    Returns ``None`` for ``off`` (or anything unknown): ThermOpt never
    propagates an off state as an order.
    """
    if value is None:
        return None
    return Z2M_TO_ORDER.get(value.strip().lower())


@dataclass(frozen=True, slots=True)
class Ladder:
    """Setpoint ladder derived from the heater's settings.

    Only Comfort and frost protection are absolute values on the heater;
    Comfort−1 and Comfort−2 are protocol offsets. Eco is *usually* Comfort
    minus 3.5 °C, but many heaters let it be set independently — pass ``eco``
    to override the derived value.
    """

    comfort: float = 20.5
    frost: float = 7.0
    eco: float | None = None

    def setpoint(self, order: Order) -> float:
        """Effective setpoint (°C) produced by ``order``."""
        if order is Order.FROST:
            return self.frost
        if order is Order.ECO and self.eco is not None:
            return round(float(self.eco), 2)
        return round(self.comfort + OFFSETS[order], 2)

    def setpoints(self) -> dict[Order, float]:
        """Full ladder, warmest first."""
        return {o: self.setpoint(o) for o in sorted(Order, key=RANK.__getitem__, reverse=True)}

    def nearest(self, target: float, *, include_frost: bool = False) -> Order:
        """Order whose effective setpoint is closest to ``target``.

        Ties are resolved towards the warmer order: comfort is a hard
        constraint, money is not.
        """
        candidates = tuple(Order) if include_frost else ACTIVE_ORDERS
        return min(
            candidates,
            key=lambda o: (abs(self.setpoint(o) - target), -RANK[o]),
        )

    def reachable(self, target: float, tolerance: float = 0.5) -> bool:
        """True when ``target`` is within ``tolerance`` of an achievable setpoint."""
        return any(abs(self.setpoint(o) - target) <= tolerance + 1e-9 for o in ACTIVE_ORDERS)

    def closest_below(self, target: float) -> Order:
        """Warmest order whose setpoint stays at or below ``target``."""
        below = [o for o in ACTIVE_ORDERS if self.setpoint(o) <= target + 1e-9]
        if not below:
            return Order.ECO
        return max(below, key=RANK.__getitem__)


def is_colder(order: Order, than: Order) -> bool:
    """True when ``order`` is colder than ``than``."""
    return RANK[order] < RANK[than]
