"""Weather forecast acquisition with graceful degradation (§ 4.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

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
    def dump(self) -> dict:
        return {
            "fetched_at": self._fetched_at.isoformat() if self._fetched_at else None,
            "points": [[stamp.isoformat(), temp] for stamp, temp in self._points],
        }

    def load(self, data: dict | None) -> None:
        if not data:
            return
        try:
            self._fetched_at = (
                dt_util.parse_datetime(data["fetched_at"]) if data.get("fetched_at") else None
            )
            self._points = [
                (dt_util.parse_datetime(stamp), float(temp))
                for stamp, temp in data.get("points", [])
            ]
        except (KeyError, TypeError, ValueError):  # pragma: no cover - corrupt storage
            _LOGGER.warning("Discarding corrupt weather cache")
            self._points = []
            self._fetched_at = None

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
        payload = (response or {}).get(self._entity_id or "", {})
        forecast = payload.get("forecast") or []

        points: list[tuple[datetime, float]] = []
        for item in forecast:
            raw_stamp = item.get("datetime")
            temperature = item.get("temperature")
            if raw_stamp is None or temperature is None:
                continue
            stamp = dt_util.parse_datetime(raw_stamp) if isinstance(raw_stamp, str) else raw_stamp
            if stamp is None:
                continue
            points.append((stamp, float(temperature)))

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
                try:
                    base = float(raw)
                except (TypeError, ValueError):
                    base = None
        if base is None:
            return []

        start = now.replace(minute=0, second=0, microsecond=0)
        points: list[tuple[datetime, float]] = []
        for hour in range(24):
            stamp = start + timedelta(hours=hour)
            angle = 2 * 3.141592653589793 * (stamp.hour - SYNTHETIC_PEAK_HOUR) / 24
            points.append((stamp, round(base + SYNTHETIC_AMPLITUDE * _cos(angle), 2)))
        return points


def _cos(angle: float) -> float:
    import math

    return math.cos(angle)


def outdoor_temperature_at(snapshot: WeatherSnapshot, moment: datetime) -> float | None:
    """Interpolate the forecast at ``moment`` (nearest hour)."""
    if not snapshot.points:
        return None
    nearest = min(snapshot.points, key=lambda p: abs((p[0] - moment).total_seconds()))
    return nearest[1]
