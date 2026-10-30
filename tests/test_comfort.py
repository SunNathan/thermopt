"""Comfort profile resolution tests."""

from __future__ import annotations

from datetime import datetime

from thermopt_lib.core.orders import Ladder, Order
from thermopt_lib.perception.comfort import (
    SLOT_DAY,
    SLOT_EVENING,
    SLOT_MORNING,
    SLOT_NIGHT,
    ComfortProfile,
    profile_issues,
    unreachable_targets,
)

MONDAY = datetime(2026, 1, 5, 12, 0)
SATURDAY = datetime(2026, 1, 10, 12, 0)


def at(hour: int, minute: int = 0, *, weekend: bool = False) -> datetime:
    base = SATURDAY if weekend else MONDAY
    return base.replace(hour=hour, minute=minute)


def test_default_slots() -> None:
    profile = ComfortProfile()
    assert profile.slot_at(at(2)) is SLOT_NIGHT
    assert profile.slot_at(at(23, 30)) is SLOT_NIGHT
    assert profile.slot_at(at(7)) is SLOT_MORNING
    assert profile.slot_at(at(10)) is SLOT_DAY
    assert profile.slot_at(at(18)) is SLOT_EVENING


def test_weekday_vs_weekend_day_floor() -> None:
    profile = ComfortProfile()
    assert profile.t_min(at(10)) == 17.0
    assert profile.t_min(at(10, weekend=True)) == 19.0


def test_presence_raises_weekday_day_floor() -> None:
    profile = ComfortProfile()
    assert profile.t_min(at(10), present=True) == 19.0
    # Presence must not affect the weekend branch or other slots.
    assert profile.t_min(at(10, weekend=True), present=True) == 19.0
    assert profile.t_min(at(2), present=True) == 17.0


def test_guard_floor_is_below_night_target() -> None:
    """With the recommended ladder, Eco holds 17 °C so the guard stays quiet."""
    profile = ComfortProfile()
    assert profile.guard_floor(at(2)) == 16.5
    ladder = Ladder(comfort=20.5)
    assert ladder.setpoint(Order.ECO) == 17.0
    assert ladder.setpoint(Order.ECO) > profile.guard_floor(at(2))


def test_band() -> None:
    profile = ComfortProfile()
    assert profile.band(at(10)) == (17.0, 18.0)


def test_ordered_slots_follow_start_times() -> None:
    profile = ComfortProfile()
    assert profile.ordered_slots == [SLOT_MORNING, SLOT_DAY, SLOT_EVENING, SLOT_NIGHT]


def test_recommended_setpoint_has_no_issue() -> None:
    profile = ComfortProfile()
    ladder = Ladder(comfort=20.5)
    assert unreachable_targets(profile, ladder) == []
    assert profile_issues(profile, ladder, ladder.setpoint(Order.ECO)) == []


def test_default_setpoint_leaves_eco_below_floor() -> None:
    """The C = 20 °C configuration of the original spec is inconsistent."""
    profile = ComfortProfile()
    ladder = Ladder(comfort=20.0)
    issues = profile_issues(profile, ladder, ladder.setpoint(Order.ECO))
    assert "eco_below_floor:17.0" in issues


def test_unreachable_target_detected() -> None:
    profile = ComfortProfile.from_config(
        weekend={SLOT_DAY: 22.0},
    )
    ladder = Ladder(comfort=20.5)
    pairs = unreachable_targets(profile, ladder)
    assert (SLOT_DAY, 22.0) in pairs
