"""Heures Creuses / Heures Pleines schedule handling.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

MINUTES_PER_DAY = 24 * 60


class InvalidWindow(ValueError):
    """Raised when a Heures Creuses window cannot be parsed."""


@dataclass(frozen=True, slots=True)
class Window:
    """An ``HH:MM -> HH:MM`` interval. ``start > end`` means it crosses midnight."""

    start: int  # minutes since midnight, inclusive
    end: int  # minutes since midnight, exclusive

    @property
    def crosses_midnight(self) -> bool:
        return self.start >= self.end

    def contains(self, minutes: int) -> bool:
        if self.crosses_midnight:
            return minutes >= self.start or minutes < self.end
        return self.start <= minutes < self.end

    def __str__(self) -> str:
        return f"{_fmt(self.start)}-{_fmt(self.end)}"


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_time(value: str) -> int:
    """Parse ``HH:MM`` into minutes since midnight."""
    raw = value.strip()
    try:
        hour_str, minute_str = raw.split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError) as err:  # pragma: no cover - defensive
        raise InvalidWindow(f"Invalid time {value!r}, expected HH:MM") from err
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise InvalidWindow(f"Time out of range: {value!r}")
    return hour * 60 + minute


def parse_windows(raw: str | list[str]) -> list[Window]:
    """Parse ``"22:00-06:00, 12:00-14:00"`` (or an already-split list)."""
    if isinstance(raw, str):
        parts = raw.replace(";", ",").split(",")
    else:
        parts = list(raw)

    windows: list[Window] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        separator = "–" if "–" in item else "-"
        if separator not in item:
            raise InvalidWindow(f"Invalid window {item!r}, expected HH:MM-HH:MM")
        start_raw, end_raw = item.split(separator, 1)
        start, end = parse_time(start_raw), parse_time(end_raw)
        if start == end:
            raise InvalidWindow(f"Empty window {item!r}")
        windows.append(Window(start, end))

    if not windows:
        raise InvalidWindow("At least one Heures Creuses window is required")

    return sorted(windows, key=lambda w: w.start)


def format_windows(windows: list[Window]) -> str:
    """Render windows back to the compact config string."""
    return ", ".join(str(w) for w in windows)


def _minutes_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def is_hc(moment: datetime, windows: list[Window]) -> bool:
    """True when ``moment`` falls inside any Heures Creuses window."""
    minutes = _minutes_of_day(moment)
    return any(w.contains(minutes) for w in windows)


def price_at(moment: datetime, windows: list[Window], hp_price: float, hc_price: float) -> float:
    """Energy price (EUR/kWh) at ``moment``."""
    return hc_price if is_hc(moment, windows) else hp_price


def next_transition(moment: datetime, windows: list[Window]) -> datetime:
    """First HC/HP boundary strictly after ``moment``."""
    minutes = _minutes_of_day(moment)
    candidates: list[int] = []
    for w in windows:
        candidates.extend((w.start, w.end))

    today = moment.replace(second=0, microsecond=0)
    best: datetime | None = None
    for offset in (0, 1):
        day = today + timedelta(days=offset)
        for candidate in candidates:
            if offset == 0 and candidate <= minutes:
                continue
            if offset == 0 and candidate == minutes:
                continue
            stamp = day.replace(hour=candidate // 60, minute=candidate % 60)
            if stamp > moment and (best is None or stamp < best):
                best = stamp
    # Explicit fallback: should never happen with non-empty windows.
    return best or today + timedelta(days=1)


def hc_duration_minutes(windows: list[Window]) -> int:
    """Total number of Heures Creuses minutes per day (sanity check)."""
    total = 0
    for w in windows:
        total += (w.end - w.start) % MINUTES_PER_DAY
    return total


def time_to_datetime(moment: datetime, value: time) -> datetime:
    """Combine the date of ``moment`` with ``value``."""
    return moment.replace(hour=value.hour, minute=value.minute, second=0, microsecond=0)
