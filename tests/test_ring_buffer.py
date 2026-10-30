"""Sampling buffer tests."""

from __future__ import annotations

from core.ring_buffer import RoomSeries


def test_append_and_len() -> None:
    series = RoomSeries()
    for index in range(3):
        series.append(float(index), t_air=20.0, power=100.0)
    assert len(series) == 3
    assert series.columns["t_air"] == [20.0, 20.0, 20.0]


def test_decimation_keeps_memory_bounded_and_doubles_step() -> None:
    series = RoomSeries(max_points=4)
    for index in range(4):
        series.append(float(index), t_air=float(index))
    assert len(series) == 4

    series.append(4.0, t_air=4.0)
    assert series.step_minutes == 10
    assert len(series) == 3  # decimated to 2, then appended
    assert series.ts == [0.0, 2.0, 4.0]
    assert series.columns["t_air"] == [0.0, 2.0, 4.0]


def test_tail_returns_recent_values_oldest_first() -> None:
    series = RoomSeries()
    for index in range(10):
        series.append(float(index * 60), t_air=float(index))
    tail = series.tail(180, now=540.0)
    assert [value for _ts, value in tail] == [6.0, 7.0, 8.0, 9.0]


def test_roundtrip() -> None:
    series = RoomSeries(step_minutes=10)
    series.append(1.0, t_air=20.5, humidity=45.0, power=1500.0, energy=2.5, order="comfort")
    restored = RoomSeries.from_dict(series.to_dict())
    assert restored.step_minutes == 10
    assert restored.ts == series.ts
    assert restored.columns["order"] == ["comfort"]


def test_from_dict_pads_missing_columns() -> None:
    restored = RoomSeries.from_dict({"ts": [1.0, 2.0], "columns": {"t_air": [20.0]}})
    assert len(restored) == 2
    assert restored.columns["t_air"] == [20.0, None]
    assert restored.columns["power"] == [None, None]
