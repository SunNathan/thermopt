"""Config and options flows for ThermOpt (UI only, no YAML)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_ENTITY,
    CONF_COMFORT_SETPOINT,
    CONF_FALLBACK_ENTITY,
    CONF_FROST_SETPOINT,
    CONF_HC_BINARY_ENTITY,
    CONF_HC_PRICE,
    CONF_HC_WINDOWS,
    CONF_HIGH_MARGIN,
    CONF_HP_PRICE,
    CONF_PRESENCE_ENTITY,
    CONF_ROOM_AREA,
    CONF_ROOM_ENERGY_ENTITY,
    CONF_ROOM_FIL_PILOTE_ENTITY,
    CONF_ROOM_HUMIDITY_ENTITY,
    CONF_ROOM_NAME,
    CONF_ROOM_NOMINAL_POWER,
    CONF_ROOM_POWER_ENTITY,
    CONF_ROOM_RELAY_ENTITY,
    CONF_ROOM_SURFACE,
    CONF_ROOM_TEMP_ENTITY,
    CONF_ROOM_VOLUME,
    CONF_START_DAY,
    CONF_START_EVENING,
    CONF_START_MORNING,
    CONF_START_NIGHT,
    CONF_T_MIN_DAY_WEEKDAY,
    CONF_T_MIN_DAY_WEEKEND,
    CONF_T_MIN_EVENING_WEEKDAY,
    CONF_T_MIN_EVENING_WEEKEND,
    CONF_T_MIN_MORNING_WEEKDAY,
    CONF_T_MIN_MORNING_WEEKEND,
    CONF_T_MIN_NIGHT_WEEKDAY,
    CONF_T_MIN_NIGHT_WEEKEND,
    CONF_T_MIN_PRESENT_DAY,
    CONF_TOLERANCE,
    CONF_WEATHER_ENTITY,
    DEFAULT_COMFORT_SETPOINT,
    DEFAULT_FALLBACK_ENTITY,
    DEFAULT_FROST_SETPOINT,
    DEFAULT_HC_PRICE,
    DEFAULT_HC_WINDOWS,
    DEFAULT_HP_PRICE,
    DEFAULT_NOMINAL_POWER,
    DOMAIN,
    SUBENTRY_ROOM,
)
from .core.orders import Ladder, Order
from .discovery import guess_room_entities
from .perception.comfort import (
    DEFAULT_HIGH_MARGIN,
    DEFAULT_PRESENT_DAY,
    DEFAULT_STARTS,
    DEFAULT_TOLERANCE,
    DEFAULT_WEEKDAY,
    DEFAULT_WEEKEND,
    SLOT_DAY,
    SLOT_EVENING,
    SLOT_MORNING,
    SLOT_NIGHT,
    ComfortProfile,
    profile_issues,
)
from .perception.tariff import InvalidWindow, parse_time, parse_windows

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def _schema(*pairs: tuple[Any, Any]) -> vol.Schema:
    """Build a schema from ``(key, selector)`` pairs."""
    return vol.Schema(dict(pairs))


def _entity(
    key: str,
    domain: str | list[str],
    default: str | None = None,
    device_class: str | None = None,
) -> tuple[Any, Any]:
    if device_class:
        config = selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    else:
        config = selector.EntitySelectorConfig(domain=domain)

    if default:
        return vol.Optional(key, default=default), selector.EntitySelector(config)
    return vol.Optional(key), selector.EntitySelector(config)


def _number(
    key: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 40.0,
    step: float = 0.1,
    unit: str | None = None,
) -> tuple[Any, Any]:
    if unit is None:
        config = selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
        )
    else:
        config = selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )

    return (
        vol.Optional(key, default=default),
        selector.NumberSelector(config),
    )


def _time(key: str, default: str) -> tuple[Any, Any]:
    return (
        vol.Optional(key, default=default),
        selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TIME)),
    )


def system_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Weather, tariff and fil pilote setpoint settings."""
    data = defaults or {}
    return _schema(
        _entity(CONF_WEATHER_ENTITY, "weather", data.get(CONF_WEATHER_ENTITY)),
        _entity(CONF_AUTO_ENTITY, "input_boolean", data.get(CONF_AUTO_ENTITY)),
        _entity(
            CONF_PRESENCE_ENTITY,
            ["input_boolean", "calendar"],
            data.get(CONF_PRESENCE_ENTITY),
        ),
        _entity(CONF_HC_BINARY_ENTITY, "binary_sensor", data.get(CONF_HC_BINARY_ENTITY)),
        _entity(
            CONF_FALLBACK_ENTITY,
            "input_boolean",
            data.get(CONF_FALLBACK_ENTITY, DEFAULT_FALLBACK_ENTITY),
        ),
        _number(
            CONF_HP_PRICE,
            float(data.get(CONF_HP_PRICE, DEFAULT_HP_PRICE)),
            minimum=0.0,
            maximum=2.0,
            step=0.001,
            unit="€/kWh",
        ),
        _number(
            CONF_HC_PRICE,
            float(data.get(CONF_HC_PRICE, DEFAULT_HC_PRICE)),
            minimum=0.0,
            maximum=2.0,
            step=0.001,
            unit="€/kWh",
        ),
        (
            vol.Optional(CONF_HC_WINDOWS, default=data.get(CONF_HC_WINDOWS, DEFAULT_HC_WINDOWS)),
            selector.TextSelector(),
        ),
        _number(
            CONF_COMFORT_SETPOINT,
            float(data.get(CONF_COMFORT_SETPOINT, DEFAULT_COMFORT_SETPOINT)),
            minimum=15.0,
            maximum=25.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_FROST_SETPOINT,
            float(data.get(CONF_FROST_SETPOINT, DEFAULT_FROST_SETPOINT)),
            minimum=5.0,
            maximum=12.0,
            step=0.5,
            unit="°C",
        ),
    )


def comfort_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Four daily slots with weekday / weekend / telework floors."""
    data = defaults or {}
    return _schema(
        _time(CONF_START_NIGHT, data.get(CONF_START_NIGHT, DEFAULT_STARTS[SLOT_NIGHT])),
        _time(CONF_START_MORNING, data.get(CONF_START_MORNING, DEFAULT_STARTS[SLOT_MORNING])),
        _time(CONF_START_DAY, data.get(CONF_START_DAY, DEFAULT_STARTS[SLOT_DAY])),
        _time(CONF_START_EVENING, data.get(CONF_START_EVENING, DEFAULT_STARTS[SLOT_EVENING])),
        _number(
            CONF_T_MIN_NIGHT_WEEKDAY,
            data.get(CONF_T_MIN_NIGHT_WEEKDAY, DEFAULT_WEEKDAY[SLOT_NIGHT]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_MORNING_WEEKDAY,
            data.get(CONF_T_MIN_MORNING_WEEKDAY, DEFAULT_WEEKDAY[SLOT_MORNING]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_DAY_WEEKDAY,
            data.get(CONF_T_MIN_DAY_WEEKDAY, DEFAULT_WEEKDAY[SLOT_DAY]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_EVENING_WEEKDAY,
            data.get(CONF_T_MIN_EVENING_WEEKDAY, DEFAULT_WEEKDAY[SLOT_EVENING]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_NIGHT_WEEKEND,
            data.get(CONF_T_MIN_NIGHT_WEEKEND, DEFAULT_WEEKEND[SLOT_NIGHT]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_MORNING_WEEKEND,
            data.get(CONF_T_MIN_MORNING_WEEKEND, DEFAULT_WEEKEND[SLOT_MORNING]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_DAY_WEEKEND,
            data.get(CONF_T_MIN_DAY_WEEKEND, DEFAULT_WEEKEND[SLOT_DAY]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_EVENING_WEEKEND,
            data.get(CONF_T_MIN_EVENING_WEEKEND, DEFAULT_WEEKEND[SLOT_EVENING]),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_T_MIN_PRESENT_DAY,
            data.get(CONF_T_MIN_PRESENT_DAY, DEFAULT_PRESENT_DAY),
            minimum=7.0,
            maximum=24.0,
            step=0.5,
            unit="°C",
        ),
        _number(
            CONF_TOLERANCE,
            data.get(CONF_TOLERANCE, DEFAULT_TOLERANCE),
            minimum=0.0,
            maximum=2.0,
            step=0.1,
            unit="K",
        ),
        _number(
            CONF_HIGH_MARGIN,
            data.get(CONF_HIGH_MARGIN, DEFAULT_HIGH_MARGIN),
            minimum=0.0,
            maximum=3.0,
            step=0.1,
            unit="K",
        ),
    )


def room_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Actuator, sensors and thermal priors for one room."""
    data = defaults or {}
    area = data.get(CONF_ROOM_AREA)
    area_key = vol.Optional(CONF_ROOM_AREA, default=area) if area else vol.Optional(CONF_ROOM_AREA)
    return _schema(
        (
            vol.Required(CONF_ROOM_NAME, default=data.get(CONF_ROOM_NAME, "")),
            selector.TextSelector(),
        ),
        (
            area_key,
            selector.AreaSelector(),
        ),
        _entity(
            CONF_ROOM_TEMP_ENTITY,
            "sensor",
            data.get(CONF_ROOM_TEMP_ENTITY),
            device_class="temperature",
        ),
        _entity(
            CONF_ROOM_HUMIDITY_ENTITY,
            "sensor",
            data.get(CONF_ROOM_HUMIDITY_ENTITY),
            device_class="humidity",
        ),
        _entity(CONF_ROOM_FIL_PILOTE_ENTITY, "select", data.get(CONF_ROOM_FIL_PILOTE_ENTITY)),
        _entity(CONF_ROOM_RELAY_ENTITY, "switch", data.get(CONF_ROOM_RELAY_ENTITY)),
        _entity(
            CONF_ROOM_POWER_ENTITY,
            "sensor",
            data.get(CONF_ROOM_POWER_ENTITY),
            device_class="power",
        ),
        _entity(
            CONF_ROOM_ENERGY_ENTITY,
            "sensor",
            data.get(CONF_ROOM_ENERGY_ENTITY),
            device_class="energy",
        ),
        _number(
            CONF_ROOM_NOMINAL_POWER,
            float(data.get(CONF_ROOM_NOMINAL_POWER, DEFAULT_NOMINAL_POWER)),
            minimum=100.0,
            maximum=4000.0,
            step=50.0,
            unit="W",
        ),
        _number(
            CONF_ROOM_SURFACE,
            float(data.get(CONF_ROOM_SURFACE, 0.0)),
            minimum=0.0,
            maximum=200.0,
            step=0.5,
            unit="m²",
        ),
        _number(
            CONF_ROOM_VOLUME,
            float(data.get(CONF_ROOM_VOLUME, 0.0)),
            minimum=0.0,
            maximum=500.0,
            step=1.0,
            unit="m³",
        ),
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _validate_system(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    try:
        parse_windows(data.get(CONF_HC_WINDOWS, DEFAULT_HC_WINDOWS))
    except InvalidWindow:
        errors[CONF_HC_WINDOWS] = "invalid_windows"

    if (
        float(data.get(CONF_FROST_SETPOINT, DEFAULT_FROST_SETPOINT))
        >= float(data.get(CONF_COMFORT_SETPOINT, DEFAULT_COMFORT_SETPOINT)) - 5
    ):
        errors[CONF_FROST_SETPOINT] = "frost_too_high"
    return errors


def _validate_comfort(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    starts: dict[str, int] = {}
    for key in (CONF_START_NIGHT, CONF_START_MORNING, CONF_START_DAY, CONF_START_EVENING):
        try:
            starts[key] = parse_time(str(data[key]))
        except (InvalidWindow, KeyError):
            errors[key] = "invalid_time"

    if not errors and len(set(starts.values())) != len(starts):
        errors[CONF_START_NIGHT] = "duplicate_slot"
    return errors


def _profile_from(data: dict[str, Any]) -> ComfortProfile:
    return ComfortProfile.from_config(
        starts={
            SLOT_NIGHT: data[CONF_START_NIGHT],
            SLOT_MORNING: data[CONF_START_MORNING],
            SLOT_DAY: data[CONF_START_DAY],
            SLOT_EVENING: data[CONF_START_EVENING],
        },
        weekday={
            SLOT_NIGHT: data[CONF_T_MIN_NIGHT_WEEKDAY],
            SLOT_MORNING: data[CONF_T_MIN_MORNING_WEEKDAY],
            SLOT_DAY: data[CONF_T_MIN_DAY_WEEKDAY],
            SLOT_EVENING: data[CONF_T_MIN_EVENING_WEEKDAY],
        },
        weekend={
            SLOT_NIGHT: data[CONF_T_MIN_NIGHT_WEEKEND],
            SLOT_MORNING: data[CONF_T_MIN_MORNING_WEEKEND],
            SLOT_DAY: data[CONF_T_MIN_DAY_WEEKEND],
            SLOT_EVENING: data[CONF_T_MIN_EVENING_WEEKEND],
        },
        present_day=data[CONF_T_MIN_PRESENT_DAY],
        tolerance=data[CONF_TOLERANCE],
        high_margin=data[CONF_HIGH_MARGIN],
    )


def _log_reachability(data: dict[str, Any]) -> None:
    """Warn (never block) when the profile does not fit the ladder."""
    try:
        profile = _profile_from(data)
        ladder = Ladder(
            comfort=float(data[CONF_COMFORT_SETPOINT]),
            frost=float(data[CONF_FROST_SETPOINT]),
        )
        issues = profile_issues(profile, ladder, ladder.setpoint(Order.ECO))
    except Exception:  # noqa: BLE001 - diagnostics must never block setup
        return

    ladder_repr = {order.value: value for order, value in ladder.setpoints().items()}
    for issue in issues:
        _LOGGER.warning(
            "Comfort profile issue '%s' with a %.1f °C Comfort setpoint (ladder: %s)",
            issue,
            ladder.comfort,
            ladder_repr,
        )


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------
class ThermOptConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: weather, tariff, setpoints."""
        if user_input is not None:
            errors = _validate_system(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_comfort()
            return self.async_show_form(
                step_id="user", data_schema=system_schema(user_input), errors=errors
            )

        return self.async_show_form(step_id="user", data_schema=system_schema())

    async def async_step_comfort(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: comfort profile."""
        if user_input is not None:
            errors = _validate_comfort(user_input)
            if not errors:
                self._data.update(user_input)
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                _log_reachability(self._data)
                return self.async_create_entry(title="ThermOpt", data=self._data)
            return self.async_show_form(
                step_id="comfort", data_schema=comfort_schema(user_input), errors=errors
            )

        return self.async_show_form(step_id="comfort", data_schema=comfort_schema())

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Minimal import support (not advertised)."""
        return await self.async_step_user(import_data)

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_ROOM: RoomSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ThermOptOptionsFlow()


class ThermOptOptionsFlow(OptionsFlow):
    """Edit system settings and the comfort profile."""

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            errors = _validate_system(user_input)
            if not errors:
                self._data = {**current, **user_input}
                return await self.async_step_comfort()
            return self.async_show_form(
                step_id="init", data_schema=system_schema(user_input), errors=errors
            )
        self._data = dict(current)
        return self.async_show_form(step_id="init", data_schema=system_schema(current))

    async def async_step_comfort(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            errors = _validate_comfort(user_input)
            if not errors:
                merged = {**self._data, **user_input}
                _log_reachability(merged)
                return self.async_create_entry(data=merged)
            return self.async_show_form(
                step_id="comfort", data_schema=comfort_schema(user_input), errors=errors
            )
        return self.async_show_form(step_id="comfort", data_schema=comfort_schema(self._data))


# ---------------------------------------------------------------------------
# Room subentry flow
# ---------------------------------------------------------------------------
class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one heated room."""

    _hints: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Entry point: manual entry or discovery from an area."""
        return self.async_show_menu(step_id="user", menu_options=["manual", "from_area"])

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            errors: dict[str, str] = {}
            if not str(user_input.get(CONF_ROOM_NAME, "")).strip():
                errors[CONF_ROOM_NAME] = "name_required"
            if not user_input.get(CONF_ROOM_FIL_PILOTE_ENTITY):
                errors[CONF_ROOM_FIL_PILOTE_ENTITY] = "actuator_required"

            if not errors:
                user_input[CONF_ROOM_NAME] = str(user_input[CONF_ROOM_NAME]).strip()
                return self.async_create_entry(title=user_input[CONF_ROOM_NAME], data=user_input)
            return self.async_show_form(
                step_id="manual", data_schema=room_schema(user_input), errors=errors
            )

        return self.async_show_form(step_id="manual", data_schema=room_schema(self._hints))

    async def async_step_from_area(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pre-fill the room form by scanning an area."""
        if user_input is not None:
            area_id = user_input.get(CONF_ROOM_AREA)
            if not area_id:
                return self.async_show_form(
                    step_id="from_area",
                    data_schema=vol.Schema({vol.Required(CONF_ROOM_AREA): selector.AreaSelector()}),
                    errors={"base": "area_required"},
                )
            self._hints = await guess_room_entities(self.hass, str(area_id))
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="from_area",
            data_schema=vol.Schema({vol.Required(CONF_ROOM_AREA): selector.AreaSelector()}),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            if not str(user_input.get(CONF_ROOM_NAME, "")).strip():
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=room_schema(user_input),
                    errors={CONF_ROOM_NAME: "name_required"},
                )
            user_input[CONF_ROOM_NAME] = str(user_input[CONF_ROOM_NAME]).strip()
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_ROOM_NAME],
                data=user_input,
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=room_schema(dict(subentry.data))
        )
