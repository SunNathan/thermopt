"""Diagnostics support: everything needed to debug a deployment."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HC_PRICE, CONF_HP_PRICE
from .coordinator import ThermOptData
from .runtime import ThermOptRuntime

TO_REDACT = {CONF_HP_PRICE, CONF_HC_PRICE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime: ThermOptRuntime = entry.runtime_data
    data = runtime.coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "version": entry.version,
        },
        "config": {
            "ladder": {
                order.value: value for order, value in runtime.config.ladder.setpoints().items()
            },
            "windows": [str(window) for window in runtime.config.windows],
            "profile": {
                "starts": dict(runtime.config.profile.starts),
                "weekday": runtime.config.profile.weekday,
                "weekend": runtime.config.profile.weekend,
                "present_day": runtime.config.profile.present_day,
                "tolerance": runtime.config.profile.tolerance,
                "high_margin": runtime.config.profile.high_margin,
            },
            "entities": {
                "weather": runtime.config.weather_entity,
                "auto": runtime.config.auto_entity,
                "presence": runtime.config.presence_entity,
                "hc_binary": runtime.config.hc_binary_entity,
            },
        },
        "cycle": {
            "status": data.status if data else None,
            "last_cycle": data.last_cycle.isoformat() if data and data.last_cycle else None,
            "next_cycle": data.next_cycle.isoformat() if data and data.next_cycle else None,
            "is_hc": data.is_hc if data else None,
            "price": data.price_now if data else None,
            "next_transition": (
                data.next_transition.isoformat() if data and data.next_transition else None
            ),
            "forecast_source": data.forecast_source if data else None,
            "forecast_points": len(runtime.weather.dump().get("points", [])),
            "degraded": list(data.degraded) if data else [],
        },
        "rooms": {
            sid: {
                "name": room.config.name,
                "enabled": room.enabled,
                "samples": len(room.series),
                "step_minutes": room.series.step_minutes,
                "entities": {
                    "temperature": room.config.temp_entity,
                    "humidity": room.config.humidity_entity,
                    "fil_pilote": room.config.fil_pilote_entity,
                    "relay": room.config.relay_entity,
                    "power": room.config.power_entity,
                    "energy": room.config.energy_entity,
                },
                "nominal_power": room.config.nominal_power,
                "surface": room.config.surface,
                "volume": room.config.volume,
                "snapshot": _room_snapshot(data, sid),
            }
            for sid, room in runtime.rooms.items()
        },
    }


def _room_snapshot(data: ThermOptData | None, subentry_id: str) -> dict[str, Any] | None:
    """Diagnostics view of one room, or ``None`` before the first cycle."""
    if data is None:
        return None
    snapshot = data.rooms.get(subentry_id)
    if snapshot is None:
        return None
    return {
        "t_air": snapshot.t_air,
        "order": snapshot.order.value if snapshot.order is not None else None,
        "target_min": snapshot.target_min,
        "guard_floor": snapshot.guard_floor,
        "degraded": list(snapshot.degraded),
    }
