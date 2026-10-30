"""Tariff window tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from perception.tariff import (
    InvalidWindow,
    Window,
    format_windows,
    hc_duration_minutes,
    is_hc,
    next_transition,
    parse_windows,
    price_at,
)

RAW = "22:00-06:00, 12:00-14:00"


def test_parse_and_format_roundtrip() -> None:
    windows = parse_windows(RAW)
    assert windows == [Window(12 * 60, 14 * 60), Window(22 * 60, 6 * 60)]
    assert format_windows(parse_windows(format_windows(windows))) == format_windows(windows)


def test_parse_accepts_list_and_semicolons() -> None:
    assert parse_windows(["22:00-06:00"]) == [Window(22 * 60, 6 * 60)]
    assert parse_windows("22:00-06:00;12:00-14:00") == parse_windows(RAW)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (23, 0, True),
        (5, 59, True),
        (6, 0, False),
        (12, 0, True),
        (13, 59, True),
        (14, 0, False),
        (15, 0, False),
        (21, 59, False),
        (22, 0, True),
    ],
)
def test_is_hc(hour: int, minute: int, expected: bool) -> None:
    assert is_hc(datetime(2026, 1, 5, hour, minute), parse_windows(RAW)) is expected


def test_price_at() -> None:
    windows = parse_windows(RAW)
    assert price_at(datetime(2026, 1, 5, 3, 0), windows, 0.2, 0.15) == 0.15
    assert price_at(datetime(2026, 1, 5, 9, 0), windows, 0.2, 0.15) == 0.2


def test_next_transition_same_day() -> None:
    windows = parse_windows(RAW)
    assert next_transition(datetime(2026, 1, 5, 21, 0), windows) == datetime(2026, 1, 5, 22, 0)


def test_next_transition_across_midnight() -> None:
    windows = parse_windows(RAW)
    assert next_transition(datetime(2026, 1, 5, 23, 30), windows) == datetime(2026, 1, 6, 6, 0)


def test_next_transition_from_inside_hc_window() -> None:
    windows = parse_windows(RAW)
    assert next_transition(datetime(2026, 1, 5, 12, 30), windows) == datetime(2026, 1, 5, 14, 0)


def test_next_transition_is_strictly_future() -> None:
    windows = parse_windows(RAW)
    moment = datetime(2026, 1, 5, 12, 0)
    assert next_transition(moment, windows) > moment


def test_hc_duration() -> None:
    assert hc_duration_minutes(parse_windows(RAW)) == 8 * 60 + 2 * 60


@pytest.mark.parametrize("raw", ["", "22:00", "25:00-06:00", "10:00-10:00", "abc-def"])
def test_invalid_windows(raw: str) -> None:
    with pytest.raises(InvalidWindow):
        parse_windows(raw)
