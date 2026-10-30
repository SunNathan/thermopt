"""Weather forecast acquisition with graceful degradation (§ 4.1)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import FORECAST_REFRESH

_LOGGER = logging.getLogger(__name__)

CACHE_TTL = FORECAST_REFRESH
SYNTHETIC_AMPLITUDE = 4.0
SYNTHETIC_PEAK_HOUR = 16


@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    """Hourly outdoor temperature forecast."""

    points: tuple[tuple[datetime, float], ...] = ()
    source: str = "none"
    fetched_at: datetime | None = None

    @property
    def available(self) -> bool:
        return bool(self.points)


class WeatherProvider:
    """Fetch ``weather.get_forecasts`` and keep the last good result.

    The cache is persisted by the runtime so a restart does not lose the
    forecast, and an unavailable integration falls back to the last known
    values plus a daily sinusoid.
    """

    def __init__(self, hass: HomeAssistant, entity_id: str | None) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._points: list[tuple[datetime, float]] = []
        self._fetched_at: datetime | None = None

    # -- persistence ---------------------------------------------------------
    def dump(self) -> dict[str, Any]:
        return {
            "fetched_at": self._fetched_at.isoformat() if self._fetched_at else None,
            "points": [[stamp.isoformat(), temp] for stamp, temp in self._points],
        }

    def load(self, data: dict[str, Any] | None) -> None:
        if not data:
            return

        fetched_at = _parse_stamp(data.get("fetched_at"))
        points = [
            point
            for point in (_parse_point(entry) for entry in data.get("points") or [])
            if point is not None
        ]

        if data.get("points") and not points:  # pragma: no cover - corrupt storage
            _LOGGER.warning("Discarding corrupt weather cache")

        self._points = points
        self._fetched_at = fetched_at

    # -- public API ----------------------------------------------------------
    async def async_snapshot(self, now: datetime) -> WeatherSnapshot:
        """Return a forecast, refreshing it at most once per hour."""
        if self._fetched_at and (now - self._fetched_at) < CACHE_TTL and self._points:
            return WeatherSnapshot(tuple(self._points), "cache", self._fetched_at)

        if self._entity_id:
            try:
                await self._async_fetch(now)
                return WeatherSnapshot(tuple(self._points), "forecast", self._fetched_at)
            except Exception as err:  # noqa: BLE001 - any failure degrades gracefully
                _LOGGER.warning("Weather forecast %s unavailable: %s", self._entity_id, err)

        if self._points:
            return WeatherSnapshot(tuple(self._points), "cache", self._fetched_at)

        synthetic = self._synthetic(now)
        return WeatherSnapshot(tuple(synthetic), "synthetic", now)

    async def _async_fetch(self, now: datetime) -> None:
        response = await self._hass.services.async_call(
            "weather",
            "get_forecasts",
            {"entity_id": self._entity_id, "type": "hourly"},
            blocking=True,
            return_response=True,
        )

        points = _extract_points(response, self._entity_id or "")
        if not points:
            raise ValueError("empty forecast")

        self._points = points
        self._fetched_at = now

    def _synthetic(self, now: datetime) -> list[tuple[datetime, float]]:
        """Daily sinusoid anchored on the current measured outdoor temperature."""
        base: float | None = None
        if self._entity_id:
            state = self._hass.states.get(self._entity_id)
            if state is not None:
                raw = state.attributes.get("temperature")
                if isinstance(raw, int | float):
                    base = float(raw)

        if base is None:
            return []

        start = now.replace(minute=0, second=0, microsecond=0)
        points: list[tuple[datetime, float]] = []
        for hour in range(24):
            stamp = start + timedelta(hours=hour)
            angle = 2 * math.pi * (stamp.hour - SYNTHETIC_PEAK_HOUR) / 24
            points.append((stamp, round(base + SYNTHETIC_AMPLITUDE * math.cos(angle), 2)))
        return points


def _parse_stamp(raw: object) -> datetime | None:
    """Parse an ISO timestamp coming from storage or a service response."""
    if not isinstance(raw, str):
        return None
    return dt_util.parse_datetime(raw)


def _parse_point(entry: object) -> tuple[datetime, float] | None:
    """Parse one ``[timestamp, temperature]`` pair from storage."""
    if not isinstance(entry, (list, tuple)) or len(entry) != 2:
        return None
    stamp = _parse_stamp(entry[0])
    temperature = entry[1]
    if stamp is None or not isinstance(temperature, int | float):
        return None
    return stamp, float(temperature)


def _extract_points(response: object, entity_id: str) -> list[tuple[datetime, float]]:
    """Validate the ``weather.get_forecasts`` payload without trusting it."""
    if not isinstance(response, dict):
        return []

    payload = response.get(entity_id)
    if not isinstance(payload, dict):
        return []

    forecast = payload.get("forecast")
    if not isinstance(forecast, list):
        return []

    points: list[tuple[datetime, float]] = []
    for item in forecast:
        if not isinstance(item, dict):
            continue
        stamp = _parse_stamp(item.get("datetime"))
        temperature = item.get("temperature")
        if stamp is None or not isinstance(temperature, int | float):
            continue
        points.append((stamp, float(temperature)))

    return points


def outdoor_temperature_at(snapshot: WeatherSnapshot, moment: datetime) -> float | None:
    """Interpolate the forecast at ``moment`` (nearest hour)."""
    if not snapshot.points:
        return None
    nearest = min(snapshot.points, key=lambda p: abs((p[0] - moment).total_seconds()))
    return nearest[1]
