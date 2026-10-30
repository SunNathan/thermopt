"""Sensor liveness tests."""

from __future__ import annotations

from thermopt_lib.perception.liveness import describe, is_frozen, is_missing

HOUR = 3600.0
WINDOW = 45 * 60


def _series(values: list[float], step: float, start: float = 0.0) -> list[tuple[float, float]]:
    return [(start + index * step, value) for index, value in enumerate(values)]


def test_frozen_detected_on_flat_window() -> None:
    samples = _series([20.0] * 10, WINDOW / 9)
    assert is_frozen(samples, window=WINDOW) is True


def test_not_frozen_when_temperature_moves() -> None:
    samples = _series([20.0, 20.0, 20.2, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0], WINDOW / 8)
    assert is_frozen(samples, window=WINDOW) is False


def test_frozen_requires_full_window() -> None:
    samples = _series([20.0] * 5, 60.0)  # only 4 minutes of history
    assert is_frozen(samples, window=WINDOW) is False


def test_frozen_ignores_missing_values() -> None:
    samples = [(0.0, None), (WINDOW / 2, 20.0), (WINDOW, None)]
    assert is_frozen(samples, window=WINDOW) is False  # not enough real samples


def test_missing() -> None:
    assert is_missing(None, 1000.0) is True
    assert is_missing(1000.0 - 60, 1000.0) is False
    assert is_missing(1000.0 - 11 * 60, 1000.0) is True


def test_describe() -> None:
    assert describe([1.0, None, 3.0]) == (1.0, 3.0)
    assert describe([None, None]) == (None, None)
