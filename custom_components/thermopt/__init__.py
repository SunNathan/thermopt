"""Home Assistant setup for the ThermOpt integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .runtime import ThermOptRuntime

_LOGGER = logging.getLogger(__name__)

type ThermOptConfigEntry = ConfigEntry[ThermOptRuntime]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Nothing to do: this integration is config-entry only."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ThermOptConfigEntry) -> bool:
    """Set up ThermOpt from a config entry."""
    runtime = ThermOptRuntime(hass, entry)
    await runtime.async_setup()
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(platform) for platform in PLATFORMS]
    )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _LOGGER.info(
        "ThermOpt ready: %s room(s), ladder %s",
        len(runtime.rooms),
        {o.value: v for o, v in runtime.config.ladder.setpoints().items()},
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ThermOptConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    if unloaded:
        await entry.runtime_data.async_shutdown()
        entry.runtime_data = None  # type: ignore[assignment]
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ThermOptConfigEntry) -> None:
    """Reload the entry on options or subentry changes.

    A full reload is required: adding or removing a room subentry changes the
    set of entities that must exist.
    """
    await hass.config_entries.async_reload(entry.entry_id)
