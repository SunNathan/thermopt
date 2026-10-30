"""Sensor liveness checks (§ 7.1.3 of the specification).

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

FROZEN_DELTA = 0.05
FROZEN_WINDOW = 45 * 60
MISSING_AFTER = 10 * 60


def is_missing(last_seen: float | None, now: float) -> bool:
    """True when no value has been received for longer than 10 minutes."""
    if last_seen is None:
        return True
    return (now - last_seen) > MISSING_AFTER


def is_frozen(
    samples: list[tuple[float, float | None]],
    *,
    window: float = FROZEN_WINDOW,
    delta: float = FROZEN_DELTA,
) -> bool:
    """True when a temperature has not moved by more than ``delta`` in ``window``.

    ``samples`` must be ``(timestamp, value)`` pairs sorted oldest first and
    covering at least ``window`` seconds, otherwise the result is ``False``
    (not enough evidence).
    """
    if not samples or len(samples) < 2:
        return False

    recent = [(ts, value) for ts, value in samples if value is not None]
    if len(recent) < 2:
        return False

    newest_ts, newest_value = recent[-1]
    oldest_ts, oldest_value = recent[0]
    if (newest_ts - oldest_ts) < window:
        return False

    values = [value for _, value in recent]
    return (max(values) - min(values)) <= delta


def describe(values: list[float | None]) -> tuple[float | None, float | None]:
    """Return ``(min, max)`` ignoring ``None``."""
    clean = [v for v in values if v is not None]
    if not clean:
        return None, None
    return min(clean), max(clean)
