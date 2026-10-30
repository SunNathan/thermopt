"""Best-effort entity discovery from a Home Assistant area.

The goal is to avoid typing six entity ids per room. Everything proposed here
is a hint: the user can override every field in the next form.

The heuristic never filters the entity selectors themselves — the controlled
entities may live in a different area than the integration.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry

from .const import (
    CONF_ROOM_AREA,
    CONF_ROOM_ENERGY_ENTITY,
    CONF_ROOM_FIL_PILOTE_ENTITY,
    CONF_ROOM_HUMIDITY_ENTITY,
    CONF_ROOM_NAME,
    CONF_ROOM_POWER_ENTITY,
    CONF_ROOM_RELAY_ENTITY,
    CONF_ROOM_TEMP_ENTITY,
)

_LOGGER = logging.getLogger(__name__)

# A NodOn SIN-4-FP-21 (and any 6-order pilot wire module) exposes this option.
FIL_PILOTE_MARKER = "frost_protection"


async def guess_room_entities(hass: HomeAssistant, area_id: str) -> dict[str, Any]:
    """Propose a room configuration for ``area_id`` (possibly empty)."""
    areas = area_registry.async_get(hass)
    area = areas.async_get_area(area_id)
    if area is None:
        return {}

    devices = device_registry.async_get(hass)
    entities = entity_registry.async_get(hass)

    hints: dict[str, Any] = {
        CONF_ROOM_AREA: area_id,
        CONF_ROOM_NAME: area.name,
    }

    device_ids = [device.id for device in device_registry.async_entries_for_area(devices, area_id)]

    by_domain: dict[str, list[tuple[str, str, str | None]]] = {}
    for device_id in device_ids:
        for entry in entity_registry.async_entries_for_device(
            entities, device_id, include_disabled_entities=False
        ):
            by_domain.setdefault(entry.domain, []).append(
                (entry.entity_id, device_id, entry.device_class or entry.original_device_class)
            )

    # 1. Pilot wire module: a select whose options carry the frost order.
    fil_pilote: tuple[str, str] | None = None
    for entity_id, device_id, _ in by_domain.get("select", []):
        state = hass.states.get(entity_id)
        options = state.attributes.get("options") if state is not None else None
        if isinstance(options, list) and FIL_PILOTE_MARKER in options:
            fil_pilote = (entity_id, device_id)
            break

    if fil_pilote is not None:
        hints[CONF_ROOM_FIL_PILOTE_ENTITY] = fil_pilote[0]
        module_device = fil_pilote[1]
        for domain, key, kind in (
            ("switch", CONF_ROOM_RELAY_ENTITY, None),
            ("sensor", CONF_ROOM_POWER_ENTITY, "power"),
            ("sensor", CONF_ROOM_ENERGY_ENTITY, "energy"),
        ):
            match = _pick(by_domain.get(domain, []), device_id=module_device, device_class=kind)
            if match:
                hints[key] = match

    # 2. Room sensors: prefer the module device, otherwise anything in the area.
    module_id = fil_pilote[1] if fil_pilote else None
    temperature = _pick(
        by_domain.get("sensor", []), device_id=module_id, device_class="temperature"
    ) or _pick(by_domain.get("sensor", []), device_class="temperature")
    if temperature:
        hints[CONF_ROOM_TEMP_ENTITY] = temperature

    humidity = _pick(
        by_domain.get("sensor", []), device_id=module_id, device_class="humidity"
    ) or _pick(by_domain.get("sensor", []), device_class="humidity")
    if humidity:
        hints[CONF_ROOM_HUMIDITY_ENTITY] = humidity

    _LOGGER.debug("Discovery for area %s: %s", area.name, hints)
    return hints


def _pick(
    candidates: list[tuple[str, str, str | None]],
    *,
    device_id: str | None = None,
    device_class: str | None = None,
) -> str | None:
    """First candidate matching the optional device and device class filters."""
    for entity_id, candidate_device, candidate_class in candidates:
        if device_id is not None and candidate_device != device_id:
            continue
        if device_class is not None and candidate_class != device_class:
            continue
        return entity_id
    return None
