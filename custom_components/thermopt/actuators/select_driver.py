"""Fil pilote actuator abstraction.

Only one implementation is needed today (NodOn SIN-4-FP-21 exposes a
``select`` entity through Zigbee2MQTT), but the interface keeps the rest of
the code independent from the hardware.
"""

from __future__ import annotations

import logging
from typing import Protocol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from ..core.limiters import WriteDecision, WriteLimiter
from ..core.orders import Order, order_from_z2m, z2m_value

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}


class FilPiloteDriver(Protocol):
    """Minimal contract for an actuator able to apply a fil pilote order."""

    @property
    def available(self) -> bool: ...

    def read(self) -> Order | None: ...

    async def async_write(self, order: Order) -> bool: ...


class SelectDriver:
    """Drive a fil pilote module exposed as a Home Assistant ``select`` entity.

    Zigbee2MQTT exposes ``pilot_wire_mode`` as a select whose options are
    ``comfort``, ``comfort_-1``, ``comfort_-2``, ``eco``, ``frost_protection``
    and ``off``. ``off`` is never emitted: it is a hard cut-off, not an order.
    """

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self.limiter = WriteLimiter()

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def available(self) -> bool:
        state = self._hass.states.get(self._entity_id)
        return state is not None and str(state.state).lower() not in UNAVAILABLE_STATES

    def read(self) -> Order | None:
        state = self._hass.states.get(self._entity_id)
        if state is None:
            return None
        return order_from_z2m(str(state.state))

    def can_write(self, target: Order) -> WriteDecision:
        """Rate limiter probe, without applying anything."""
        return self.limiter.check(dt_util.now(), self.read(), target)

    async def async_write(self, order: Order) -> bool:
        """Apply ``order``; returns True when the service call succeeded."""
        if not self.available:
            raise HomeAssistantError(f"{self._entity_id} is unavailable")

        value = z2m_value(order)
        state = self._hass.states.get(self._entity_id)
        if state is not None:
            supported = state.attributes.get("options")
            if supported and value not in supported:
                raise HomeAssistantError(
                    f"{self._entity_id} does not support '{value}' (options: {supported})"
                )

        await self._hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": self._entity_id, "option": value},
            blocking=True,
        )
        _LOGGER.debug("Applied fil pilote order %s (%s)", order.value, value)
        self.limiter.record(dt_util.now())
        return True


__all__ = ["FilPiloteDriver", "SelectDriver", "WriteDecision", "WriteLimiter"]
