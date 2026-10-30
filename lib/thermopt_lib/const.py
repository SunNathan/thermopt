"""Degradation flags, shared with the reporting module.

The app has no configuration keys of its own here: everything user-facing lives
in ``/data/config.json``, validated by ``app.config``.
"""

from __future__ import annotations

DEGRADED_WEATHER = "weather_unavailable"
DEGRADED_SENSOR_MISSING = "sensor_missing"
DEGRADED_SENSOR_FROZEN = "sensor_frozen"
DEGRADED_ACTUATOR_UNAVAILABLE = "actuator_unavailable"
DEGRADED_RELAY_OFF = "relay_off"
DEGRADED_TARIFF_MISMATCH = "tariff_mismatch"
DEGRADED_PROFILE_UNREACHABLE = "profile_unreachable"
DEGRADED_NO_ROOM = "no_room_configured"
DEGRADED_NO_EFFECT = "no_effect"
DEGRADED_DISK = "disk_low"
