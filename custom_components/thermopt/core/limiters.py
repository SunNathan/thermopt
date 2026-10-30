"""Write rate limiting (dwell time + maximum change rate).

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DWELL = timedelta(minutes=5)
WINDOW = timedelta(minutes=30)
MAX_CHANGES = 1


@dataclass(frozen=True, slots=True)
class WriteDecision:
    """Outcome of the rate limiter."""

    allowed: bool
    reason: str = ""


class WriteLimiter:
    """Enforce dwell time and maximum change rate (§ 6.1 of the spec).

    A heater needs a stable order for several minutes to decode it, so two
    consecutive changes must be at least ``dwell`` apart, and no more than
    ``max_changes`` changes may happen within ``window``.
    """

    def __init__(
        self,
        dwell: timedelta = DWELL,
        window: timedelta = WINDOW,
        max_changes: int = MAX_CHANGES,
    ) -> None:
        self._dwell = dwell
        self._window = window
        self._max_changes = max_changes
        self._writes: list[datetime] = []

    def check(self, now: datetime, current: object | None, target: object) -> WriteDecision:
        """Decide whether ``target`` may be applied now."""
        if current is target:
            return WriteDecision(False, "unchanged")

        recent = [stamp for stamp in self._writes if (now - stamp) < self._window]
        self._writes = recent

        if recent and (now - recent[-1]) < self._dwell:
            return WriteDecision(False, "dwell_time")

        if len(recent) >= self._max_changes:
            return WriteDecision(False, "rate_limit")

        return WriteDecision(True)

    def record(self, now: datetime) -> None:
        """Register a successful write at ``now``."""
        self._writes.append(now)
        self._writes = [stamp for stamp in self._writes if (now - stamp) < self._window]

    def reset(self) -> None:
        self._writes.clear()

    @property
    def last_write(self) -> datetime | None:
        return self._writes[-1] if self._writes else None
