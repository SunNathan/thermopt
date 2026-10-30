"""Comfort profile resolution.

Four daily slots (night / morning / day / evening) with distinct setpoint
floors for weekdays, weekends, and weekday teleworking.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .tariff import parse_time

SLOT_NIGHT = "night"
SLOT_MORNING = "morning"
SLOT_DAY = "day"
SLOT_EVENING = "evening"
SLOTS: tuple[str, ...] = (SLOT_NIGHT, SLOT_MORNING, SLOT_DAY, SLOT_EVENING)

DEFAULT_STARTS: dict[str, str] = {
    SLOT_NIGHT: "23:00",
    SLOT_MORNING: "06:30",
    SLOT_DAY: "08:30",
    SLOT_EVENING: "17:30",
}

# Reference values from the specification (§ 9.1).
DEFAULT_WEEKDAY: dict[str, float] = {
    SLOT_NIGHT: 17.0,
    SLOT_MORNING: 19.5,
    SLOT_DAY: 17.0,
    SLOT_EVENING: 19.5,
}
DEFAULT_WEEKEND: dict[str, float] = {
    SLOT_NIGHT: 17.0,
    SLOT_MORNING: 19.5,
    SLOT_DAY: 19.0,
    SLOT_EVENING: 19.5,
}
DEFAULT_PRESENT_DAY = 19.0
DEFAULT_TOLERANCE = 0.3
DEFAULT_HIGH_MARGIN = 1.0

# Hard floor never breached, whatever the profile says (§ 6.1).
ABSOLUTE_FLOOR = 7.0


@dataclass(frozen=True, slots=True)
class ComfortProfile:
    """Resolved comfort profile."""

    starts: dict[str, int] = field(
        default_factory=lambda: {k: parse_time(v) for k, v in DEFAULT_STARTS.items()}
    )
    weekday: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEEKDAY))
    weekend: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEEKEND))
    present_day: float = DEFAULT_PRESENT_DAY
    tolerance: float = DEFAULT_TOLERANCE
    high_margin: float = DEFAULT_HIGH_MARGIN

    @classmethod
    def from_config(
        cls,
        starts: dict[str, str] | None = None,
        weekday: dict[str, float] | None = None,
        weekend: dict[str, float] | None = None,
        present_day: float = DEFAULT_PRESENT_DAY,
        tolerance: float = DEFAULT_TOLERANCE,
        high_margin: float = DEFAULT_HIGH_MARGIN,
    ) -> ComfortProfile:
        parsed = {k: parse_time(v) for k, v in DEFAULT_STARTS.items()}
        for slot, raw in (starts or {}).items():
            if slot in SLOTS and raw:
                parsed[slot] = parse_time(raw)
        return cls(
            starts=parsed,
            weekday={**DEFAULT_WEEKDAY, **(weekday or {})},
            weekend={**DEFAULT_WEEKEND, **(weekend or {})},
            present_day=present_day,
            tolerance=tolerance,
            high_margin=high_margin,
        )

    @property
    def ordered_slots(self) -> list[str]:
        """Slots sorted by start time."""
        return sorted(SLOTS, key=self.starts.__getitem__)

    def slot_at(self, moment: datetime) -> str:
        """Active slot name at ``moment``."""
        minutes = moment.hour * 60 + moment.minute
        current = self.ordered_slots[0]
        for slot in self.ordered_slots:
            if self.starts[slot] <= minutes:
                current = slot
            else:
                break
        if minutes < self.starts[self.ordered_slots[0]]:
            # Before the first slot of the day: we are in the slot that wraps.
            current = self.ordered_slots[-1]
        return current

    def t_min(self, moment: datetime, *, present: bool = False) -> float:
        """Comfort lower bound (°C) at ``moment``."""
        slot = self.slot_at(moment)
        if moment.weekday() >= 5:
            return self.weekend[slot]
        if present and slot == SLOT_DAY:
            return self.present_day
        return self.weekday[slot]

    def band(self, moment: datetime, *, present: bool = False) -> tuple[float, float]:
        """Allowed band ``(T_min, T_max)`` where T_max is the preheat ceiling."""
        low = self.t_min(moment, present=present)
        return low, round(low + self.high_margin, 2)

    def guard_floor(self, moment: datetime, *, present: bool = False) -> float:
        """Absolute floor below which Confort is forced (§ 7.1.1).

        Defined on the *achievable* setpoint, not on the ideal target, so a
        quantised ladder cannot make the guard fire every night.
        """
        return round(max(self.t_min(moment, present=present) - 0.5, ABSOLUTE_FLOOR), 2)


def unreachable_targets(
    profile: ComfortProfile, ladder, tolerance: float = 0.5
) -> list[tuple[str, float]]:
    """Return ``(slot, target)`` pairs the ladder cannot honour.

    ``ladder`` is a ``core.orders.Ladder``; typed loosely to keep this module
    dependency-free. The default tolerance is 0.5 K, the smallest quantisation
    step a 4-order protocol can express.
    """
    seen: dict[float, str] = {}
    for slot in SLOTS:
        for target in (
            profile.weekday[slot],
            profile.weekend[slot],
        ):
            if not ladder.reachable(target, tolerance):
                seen.setdefault(target, slot)
    if not ladder.reachable(profile.present_day, tolerance):
        seen.setdefault(profile.present_day, SLOT_DAY)
    return [(slot, target) for target, slot in seen.items()]


def profile_issues(
    profile: ComfortProfile,
    ladder,
    lowest_active: float | None = None,
    tolerance: float = 0.5,
) -> list[str]:
    """Human-readable consistency problems between profile and ladder.

    Two failure modes are detected:

    * ``unreachable`` — a target sits more than ``tolerance`` away from every
      achievable setpoint.
    * ``eco_below_floor`` — the coldest usable order is below the comfort
      floor, which means either under-heating or a guard rail firing on every
      night cycle. This is the ``C = 20 °C`` trap: Eco lands on 16.5 °C while
      the night floor is 17 °C.
    """
    issues = [
        f"unreachable:{target:.1f}"
        for _slot, target in unreachable_targets(profile, ladder, tolerance)
    ]

    targets = {profile.weekday[slot] for slot in SLOTS} | {profile.weekend[slot] for slot in SLOTS}
    targets.add(profile.present_day)
    floor = min(targets)
    if lowest_active is not None and lowest_active < floor - 0.4:
        issues.append(f"eco_below_floor:{floor:.1f}")

    return issues
