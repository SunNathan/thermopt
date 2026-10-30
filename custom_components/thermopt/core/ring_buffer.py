"""Fixed-size, down-sampling time series used for temperature/power history.

Pure Python: no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SAMPLE_FIELDS = ("t_air", "humidity", "power", "energy", "order")


@dataclass(slots=True)
class RoomSeries:
    """Column-oriented ring buffer for one room.

    When the buffer is full it is decimated by two: every second sample is
    dropped and ``step_minutes`` doubles, so memory stays bounded while the
    covered time span keeps growing (5 min -> 10 min -> 15 min -> ...).
    """

    max_points: int = 26280
    step_minutes: int = 5
    ts: list[float] = field(default_factory=list)
    columns: dict[str, list[Any]] = field(
        default_factory=lambda: {name: [] for name in SAMPLE_FIELDS}
    )

    def append(
        self,
        ts: float,
        t_air: float | None = None,
        humidity: float | None = None,
        power: float | None = None,
        energy: float | None = None,
        order: str | None = None,
    ) -> None:
        """Append one sample, decimating first when the buffer is full."""
        if len(self.ts) >= self.max_points:
            self._decimate()
        self.ts.append(ts)
        self.columns["t_air"].append(t_air)
        self.columns["humidity"].append(humidity)
        self.columns["power"].append(power)
        self.columns["energy"].append(energy)
        self.columns["order"].append(order)

    def _decimate(self) -> None:
        self.ts = self.ts[::2]
        for name in SAMPLE_FIELDS:
            self.columns[name] = self.columns[name][::2]
        self.step_minutes *= 2

    def __len__(self) -> int:
        return len(self.ts)

    def tail(self, seconds: float, now: float) -> list[tuple[float, Any]]:
        """Return ``(ts, t_air)`` pairs newer than ``now - seconds``."""
        threshold = now - seconds
        out: list[tuple[float, Any]] = []
        for ts, value in zip(reversed(self.ts), reversed(self.columns["t_air"]), strict=True):
            if ts < threshold:
                break
            out.append((ts, value))
        out.reverse()
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_points": self.max_points,
            "step_minutes": self.step_minutes,
            "ts": self.ts,
            "columns": self.columns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoomSeries:
        ts = list(data.get("ts", []))
        size = len(ts)
        columns: dict[str, list[Any]] = {}
        for name in SAMPLE_FIELDS:
            values = list(data.get("columns", {}).get(name, []))
            if len(values) < size:
                values.extend([None] * (size - len(values)))
            columns[name] = values[:size]
        return cls(
            max_points=int(data.get("max_points", 26280)),
            step_minutes=int(data.get("step_minutes", 5)),
            ts=ts,
            columns=columns,
        )
