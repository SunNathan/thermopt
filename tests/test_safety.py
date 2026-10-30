"""Pure tests for the safety layer."""

from __future__ import annotations

from datetime import datetime, timedelta

from thermopt_lib.core.orders import Order
from thermopt_lib.core.safety import (
    ABSOLUTE_FLOOR,
    GUARD_MARGIN,
    SafetyState,
    detect_window,
    evaluate,
    guard_thresholds,
    manual_hold,
)

NOW = datetime(2026, 1, 5, 3, 0)  # Monday, 03:00
T_MIN = 17.0


def decision(**overrides):
    kwargs = {
        "now": NOW,
        "t_air": 19.0,
        "t_min": T_MIN,
        "current": Order.ECO,
        "armed": False,
        "suspended_until": None,
        "manual_hold_until": None,
        "window_open": False,
    }
    kwargs.update(overrides)
    return evaluate(**kwargs)


def test_thresholds() -> None:
    arm, release = guard_thresholds(T_MIN)
    assert arm == T_MIN - GUARD_MARGIN
    assert release > arm


def test_idle_when_comfort_respected() -> None:
    result = decision(t_air=19.0)
    assert result.state is SafetyState.IDLE
    assert result.order is None
    assert result.armed is False


def test_floor_forces_comfort() -> None:
    result = decision(t_air=16.0)
    assert result.state is SafetyState.FLOOR
    assert result.order is Order.COMFORT
    assert result.escalate is True  # arming may bypass the rate window
    assert result.armed is True


def test_floor_does_not_re_escalate_when_already_armed() -> None:
    result = decision(t_air=16.0, armed=True)
    assert result.order is Order.COMFORT
    assert result.escalate is False


def test_hysteresis_keeps_the_guard_armed() -> None:
    """Just above the arm threshold, an armed guard keeps holding."""
    arm, release = guard_thresholds(T_MIN)
    result = decision(t_air=arm + 0.1, armed=True)
    assert result.state is SafetyState.FLOOR
    assert result.order is Order.COMFORT
    assert result.armed is True


def test_hysteresis_releases_above_the_release_threshold() -> None:
    _, release = guard_thresholds(T_MIN)
    result = decision(t_air=release + 0.1, armed=True)
    assert result.state is SafetyState.IDLE
    assert result.order is None
    assert result.armed is False


def test_frost_wins_over_everything() -> None:
    result = decision(
        t_air=ABSOLUTE_FLOOR - 1,
        manual_hold_until=NOW + timedelta(hours=1),
        suspended_until=NOW + timedelta(minutes=30),
    )
    assert result.state is SafetyState.FROST
    assert result.order is Order.COMFORT
    assert result.escalate is True


def test_manual_hold_blocks_the_floor_guard() -> None:
    result = decision(t_air=16.0, manual_hold_until=NOW + timedelta(minutes=30))
    assert result.state is SafetyState.MANUAL
    assert result.order is None


def test_manual_hold_expires() -> None:
    result = decision(t_air=16.0, manual_hold_until=NOW - timedelta(minutes=1))
    assert result.state is SafetyState.FLOOR
    assert result.order is Order.COMFORT


def test_suspension_blocks_writes() -> None:
    result = decision(t_air=16.0, suspended_until=NOW + timedelta(minutes=10))
    assert result.state is SafetyState.WINDOW
    assert result.order is None


def test_window_detection_requests_suspension() -> None:
    result = decision(t_air=17.5, window_open=True)
    assert result.state is SafetyState.WINDOW
    assert result.suspend_until == NOW + timedelta(minutes=60)


def test_window_is_ignored_once_expired() -> None:
    result = decision(t_air=17.5, suspended_until=NOW - timedelta(minutes=1))
    assert result.state is SafetyState.IDLE


def test_missing_temperature_does_nothing() -> None:
    result = decision(t_air=None)
    assert result.state is SafetyState.IDLE
    assert result.order is None


def test_detect_window() -> None:
    samples = [(0.0, 20.0), (300.0, 19.5), (600.0, 18.2)]
    assert detect_window(samples, NOW) is True


def test_detect_window_needs_enough_points() -> None:
    assert detect_window([(0.0, 20.0), (600.0, 16.0)], NOW) is False


def test_detect_window_ignores_missing_values() -> None:
    samples = [(0.0, None), (300.0, 20.0), (600.0, None)]
    assert detect_window(samples, NOW) is False


def test_detect_window_no_drop() -> None:
    samples = [(0.0, 20.0), (300.0, 20.3), (600.0, 20.1)]
    assert detect_window(samples, NOW) is False


def test_manual_hold_duration() -> None:
    assert manual_hold(NOW) == NOW + timedelta(minutes=120)
