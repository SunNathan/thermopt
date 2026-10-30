"""Atomic JSON persistence in the app's private ``/data`` folder."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_PATH = Path("/data/config.json")


class JsonStore:
    """Read and write a single JSON document, never leaving a half-written file."""

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as err:
            _LOGGER.error("Cannot read %s: %s", self.path, err)
            return None
        return payload if isinstance(payload, dict) else None

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        _LOGGER.debug("Saved %s", self.path)

    def backup(self) -> Path | None:
        """Keep the previous version around, once per save, for safety."""
        if not self.path.exists():
            return None
        target = self.path.with_suffix(".bak")
        try:
            target.write_bytes(self.path.read_bytes())
        except OSError as err:  # pragma: no cover - disk full and friends
            _LOGGER.warning("Cannot back up %s: %s", self.path, err)
            return None
        return target
