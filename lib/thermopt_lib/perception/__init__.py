"""Package init for perception helpers (mixed pure/HA modules)."""

from __future__ import annotations

from .comfort import SLOT_DAY, SLOT_EVENING, SLOT_MORNING, SLOT_NIGHT, ComfortProfile
from .tariff import Window, is_hc, next_transition, parse_windows, price_at

__all__ = [
    "ComfortProfile",
    "SLOT_DAY",
    "SLOT_EVENING",
    "SLOT_MORNING",
    "SLOT_NIGHT",
    "Window",
    "is_hc",
    "next_transition",
    "parse_windows",
    "price_at",
]
