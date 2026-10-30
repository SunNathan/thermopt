"""Tests for the history store: retention, filtering and disk watch."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.history import DISK_MIN_FREE, RETENTION_MONTHS, HistoryStore, to_csv

RECORD = {
    "ts": "2026-01-15T10:00:00",
    "room": "aaa",
    "t_air": 20.1,
    "t_ext": 4.0,
    "order": "comfort",
    "power": 800.0,
    "energy": 12.0,
    "target_min": 19.5,
}


def _store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(tmp_path)


def test_append_creates_one_file_per_month(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append([RECORD])
    store.append([{**RECORD, "ts": "2026-02-02T10:00:00"}])

    assert sorted(path.name for path in store.files()) == ["2026-01.jsonl", "2026-02.jsonl"]


def test_read_returns_everything_sorted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append([{**RECORD, "ts": "2026-02-02T10:00:00"}, RECORD])

    records = store.read()
    assert [record["ts"] for record in records] == [
        "2026-01-15T10:00:00",
        "2026-02-02T10:00:00",
    ]


def test_read_filters_on_a_date_range(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(
        [
            {**RECORD, "ts": "2026-01-01T00:00:00"},
            {**RECORD, "ts": "2026-01-15T00:00:00"},
            {**RECORD, "ts": "2026-02-01T00:00:00"},
        ]
    )

    records = store.read(since=datetime(2026, 1, 10), until=datetime(2026, 1, 31, 23, 59))
    assert [record["ts"] for record in records] == ["2026-01-15T00:00:00"]


def test_read_filters_on_room(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append([RECORD, {**RECORD, "room": "bbb"}])

    assert len(store.read(room="bbb")) == 1


def test_prune_keeps_the_current_month_and_two_previous(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for month in (9, 10, 11, 12):
        store.append([{**RECORD, "ts": f"2026-{month:02d}-10T10:00:00"}])

    removed = store.prune(now=datetime(2026, 12, 15))

    remaining = sorted(path.name for path in store.files())
    assert removed == ["2026-09.jsonl"]
    assert remaining == ["2026-10.jsonl", "2026-11.jsonl", "2026-12.jsonl"]


def test_prune_crosses_the_year_boundary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for month in (11, 12):
        store.append([{**RECORD, "ts": f"2026-{month:02d}-10T10:00:00"}])
    store.append([{**RECORD, "ts": "2027-01-05T10:00:00"}])

    store.prune(now=datetime(2027, 1, 10))

    assert sorted(path.name for path in store.files()) == [
        "2026-11.jsonl",
        "2026-12.jsonl",
        "2027-01.jsonl",
    ]


def test_prune_never_removes_the_current_month(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append([RECORD])
    assert store.prune(now=datetime(2026, 1, 20)) == []
    assert len(store.files()) == 1


def test_file_range_reports_the_months(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.file_range() is None

    store.append([RECORD, {**RECORD, "ts": "2026-03-01T00:00:00"}])
    assert store.file_range() == ("2026-01", "2026-03")


def test_disk_watch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.refresh_disk()

    assert store.free_bytes is not None and store.free_bytes > 0
    assert store.low_disk() is False

    store.free_bytes = DISK_MIN_FREE - 1
    assert store.low_disk() is True


def test_retention_constant() -> None:
    assert RETENTION_MONTHS == 2


def test_csv_export(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append([RECORD])

    body = to_csv(store.read())
    lines = body.strip().splitlines()

    assert lines[0].startswith("ts,room,t_air")
    assert lines[1].startswith("2026-01-15T10:00:00,aaa,20.1")


def test_csv_export_handles_missing_values(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append([{**RECORD, "energy": None}])

    assert ",," in to_csv(store.read())
