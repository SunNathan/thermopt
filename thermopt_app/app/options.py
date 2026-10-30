"""App options, read from ``/data/options.json``.

Pure Python: no network, no Home Assistant import. The Supervisor writes the
options file and restarts the app when they change.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIONS_PATH = Path("/data/options.json")
LOG_LEVELS = ("debug", "info", "warning", "error")
DEFAULT_LOG_LEVEL = "info"


@dataclass(frozen=True, slots=True)
class Options:
    """Everything the app can be told to do from the add-on page."""

    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def parse(cls, raw: dict | None) -> Options:
        """Build options from the supervisor payload, ignoring bad values."""
        level = str((raw or {}).get("log_level", DEFAULT_LOG_LEVEL)).lower()
        if level not in LOG_LEVELS:
            level = DEFAULT_LOG_LEVEL
        return cls(log_level=level)

    @classmethod
    def load(cls, path: Path = DEFAULT_OPTIONS_PATH) -> Options:
        """Read the options file; a missing file is not an error."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _LOGGER.warning("%s not found, using defaults", path)
            return cls()
        except (OSError, ValueError) as err:
            _LOGGER.warning("Invalid options file %s: %s", path, err)
            return cls()

        if not isinstance(payload, dict):
            _LOGGER.warning("Options file is not an object, using defaults")
            return cls()
        return cls.parse(payload)
