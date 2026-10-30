"""Home Assistant Core client, through the Supervisor proxy.

The proxy gives administrator rights, so every call must be deliberate. States
are cached briefly: the configuration page lists every entity, and the loop
reads a handful of them per cycle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from .supervisor import SupervisorClient, SupervisorError

_LOGGER = logging.getLogger(__name__)

STATES_TTL = 20


@dataclass(frozen=True, slots=True)
class EntityState:
    """Minimal view of a Home Assistant state."""

    entity_id: str
    state: str
    attributes: dict[str, Any]

    @property
    def available(self) -> bool:
        return self.state not in ("unavailable", "unknown", "none", "")

    def as_float(self) -> float | None:
        try:
            return float(self.state)
        except (TypeError, ValueError):
            return None


class HaClient:
    """Everything the app needs from Home Assistant, and nothing more."""

    def __init__(self, supervisor: SupervisorClient) -> None:
        self._api = supervisor
        self._states: dict[str, EntityState] = {}
        self._fetched_at = 0.0

    # -- states --------------------------------------------------------------
    async def refresh_states(self) -> dict[str, EntityState]:
        payload = await self._api.get("/core/api/states")
        if not isinstance(payload, list):
            raise SupervisorError("unexpected /core/api/states payload")

        states: dict[str, EntityState] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            attributes = item.get("attributes")
            states[entity_id] = EntityState(
                entity_id=entity_id,
                state=str(item.get("state", "")),
                attributes=attributes if isinstance(attributes, dict) else {},
            )

        self._states = states
        self._fetched_at = time.monotonic()
        return states

    async def states(self) -> dict[str, EntityState]:
        if time.monotonic() - self._fetched_at > STATES_TTL:
            return await self.refresh_states()
        return self._states

    async def state(self, entity_id: str | None) -> EntityState | None:
        if not entity_id:
            return None
        states = await self.states()
        return states.get(entity_id)

    async def numeric(self, entity_id: str | None) -> float | None:
        state = await self.state(entity_id)
        return state.as_float() if state is not None else None

    async def is_on(self, entity_id: str | None) -> bool:
        state = await self.state(entity_id)
        return state is not None and state.state.lower() == "on"

    def cached(self) -> dict[str, EntityState]:
        """Last fetched states, for the web pages (never blocks on I/O)."""
        return self._states

    # -- services ------------------------------------------------------------
    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self._api.post(f"/core/api/services/{domain}/{service}", data)
        # The cache is stale now; force a refresh on next access.
        self._fetched_at = 0.0

    async def select_option(self, entity_id: str, option: str) -> None:
        await self.call_service(
            "select", "select_option", {"entity_id": entity_id, "option": option}
        )

    # -- weather -------------------------------------------------------------
    async def hourly_forecast(self, entity_id: str) -> list[tuple[float, float]]:
        """Hourly temperatures as ``(timestamp, °C)`` pairs."""
        payload = await self._api.post(
            "/core/api/services/weather/get_forecasts?return_response=true",
            {"entity_id": entity_id, "type": "hourly"},
        )
        points = extract_forecast(payload, entity_id)
        if not points:
            raise SupervisorError("prévision vide ou illisible")
        return points


def extract_forecast(payload: object, entity_id: str) -> list[tuple[float, float]]:
    """Read the forecast out of a REST service response.

    Home Assistant wraps the payload of a ``return_response`` call::

        {"changed_states": [...],
         "service_response": {"weather.x": {"forecast": [...]}}}

    The unwrapped form is accepted too, so the parser survives either shape.
    """
    if not isinstance(payload, dict):
        return []

    inner = payload.get("service_response", payload)
    if not isinstance(inner, dict):
        return []

    service = inner.get(entity_id)
    if not isinstance(service, dict):
        return []

    forecast = service.get("forecast")
    if not isinstance(forecast, list):
        return []

    points: list[tuple[float, float]] = []
    for item in forecast:
        if not isinstance(item, dict):
            continue
        stamp = item.get("datetime")
        temperature = item.get("temperature")
        if not isinstance(stamp, str) or not isinstance(temperature, int | float):
            continue
        parsed = _parse_iso(stamp)
        if parsed is not None:
            points.append((parsed, float(temperature)))

    return points


def _parse_iso(value: str) -> float | None:
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
