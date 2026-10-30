"""Diagnostic buttons: force a cycle, dump the internal state."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .dashboard import build_dashboard_yaml, collect, summary, validate_dashboard_yaml
from .entity import ThermOptEntity, hub_device_info
from .runtime import ThermOptRuntime

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ThermOptRuntime = entry.runtime_data
    async_add_entities(
        [
            ThermOptRunNowButton(runtime),
            ThermOptDumpButton(runtime),
            ThermOptDashboardButton(runtime),
        ]
    )


class _ThermOptButton(ThermOptEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: ThermOptRuntime, key: str, name: str, icon: str) -> None:
        super().__init__(runtime, key)
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = hub_device_info(runtime)


class ThermOptRunNowButton(_ThermOptButton):
    """Run a supervision cycle immediately."""

    def __init__(self, runtime: ThermOptRuntime) -> None:
        super().__init__(runtime, "run_now", "Exécuter un cycle", "mdi:play-circle-outline")

    async def async_press(self, **kwargs: Any) -> None:
        await self.coordinator.async_refresh()


class ThermOptDashboardButton(_ThermOptButton):
    """Emit a Lovelace view built from the real entity ids."""

    def __init__(self, runtime: ThermOptRuntime) -> None:
        super().__init__(
            runtime, "generate_dashboard", "Générer la vue", "mdi:view-dashboard-outline"
        )

    async def async_press(self, **kwargs: Any) -> None:
        from homeassistant.components import persistent_notification

        data = collect(self.runtime.hass, self.runtime)
        yaml_text = build_dashboard_yaml(data)
        error = validate_dashboard_yaml(yaml_text)

        if error:
            body = (
                f"Le YAML généré est invalide, il n'a pas été publié.\n\n**{error}**\n\n"
                f"```yaml\n{yaml_text}```"
            )
        else:
            body = (
                f"{summary(data)}\n\n"
                "**Paramètres → Tableaux de bord → ⋯ → Modifier → ⋯ → "
                "Éditeur de configuration brute**, puis **tout sélectionner** et coller "
                "ce bloc à la place :\n\n"
                f"```yaml\n{yaml_text}```"
            )

        _LOGGER.info(
            "ThermOpt dashboard for entry %s (valid=%s):\n%s",
            self.runtime.entry.entry_id,
            error is None,
            yaml_text,
        )
        persistent_notification.async_create(
            self.runtime.hass,
            body,
            title="ThermOpt — tableau de bord à coller",
            notification_id="thermopt_dashboard",
        )


class ThermOptDumpButton(_ThermOptButton):
    """Log the internal state (buffer sizes, ladder, thresholds)."""

    def __init__(self, runtime: ThermOptRuntime) -> None:
        super().__init__(runtime, "dump_state", "Dumper l'état", "mdi:bug-outline")

    async def async_press(self, **kwargs: Any) -> None:
        runtime = self.runtime
        data = self.coordinator.data
        _LOGGER.info(
            "ThermOpt state: status=%s degraded=%s ladder=%s windows=%s rooms=%s",
            data.status if data else None,
            list(data.degraded) if data else [],
            {o.value: v for o, v in runtime.config.ladder.setpoints().items()},
            [str(w) for w in runtime.config.windows],
            {
                sid: {
                    "enabled": room.enabled,
                    "samples": len(room.series),
                    "step_minutes": room.series.step_minutes,
                    "order": room.order.value if room.order else None,
                }
                for sid, room in runtime.rooms.items()
            },
        )
