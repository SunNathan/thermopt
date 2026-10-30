"""Append-only history of the supervision loop.

One JSONL file per month, one line per room per cycle. Appending is the only
write: no full rewrite, so a power cut can lose at most the last line.

The recorder cannot help here — it purges raw states after ``purge_keep_days``
and a ``select`` has no long-term statistics, so the fil pilote order only
exists in this file.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_ROOT = Path("/data/history")
FIELDS = ("ts", "room", "t_air", "t_ext", "order", "power", "energy", "target_min")


def month_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


class HistoryStore:
    """Read and append the monthly files."""

    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root

    # -- files ---------------------------------------------------------------
    def files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.glob("*.jsonl"))

    def path_for(self, moment: datetime) -> Path:
        return self.root / f"{month_key(moment)}.jsonl"

    # -- writing -------------------------------------------------------------
    def append(self, records: Iterable[dict[str, Any]]) -> int:
        """Blocking append; call it through ``asyncio.to_thread``."""
        self.root.mkdir(parents=True, exist_ok=True)

        grouped: dict[Path, list[str]] = {}
        count = 0
        for record in records:
            stamp = record.get("ts")
            moment = _parse(stamp)
            if moment is None:
                continue
            line = json.dumps(
                {key: record.get(key) for key in FIELDS},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            grouped.setdefault(self.path_for(moment), []).append(line)
            count += 1

        for path, lines in grouped.items():
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write("\n".join(lines) + "\n")
            except OSError as err:  # pragma: no cover - disk full and friends
                _LOGGER.error("Écriture historique impossible dans %s : %s", path, err)
        return count

    async def async_append(self, records: Iterable[dict[str, Any]]) -> int:
        return await asyncio.to_thread(self.append, list(records))

    # -- reading -------------------------------------------------------------
    def read(self, *, room: str | None = None, since: datetime | None = None) -> list[dict]:
        records: list[dict] = []
        for path in self.files():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        if room is not None and record.get("room") != room:
                            continue
                        if since is not None:
                            stamp = _parse(record.get("ts"))
                            if stamp is None or stamp < since:
                                continue
                        records.append(record)
            except OSError as err:  # pragma: no cover
                _LOGGER.warning("Lecture impossible de %s : %s", path, err)

        records.sort(key=lambda item: str(item.get("ts")))
        return records

    async def async_read(self, *, room: str | None = None, since: datetime | None = None):
        return await asyncio.to_thread(self.read, room=room, since=since)

    def size(self) -> int:
        return sum(path.stat().st_size for path in self.files() if path.exists())


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def to_csv(records: list[dict]) -> str:
    """Comma-separated export, for offline work."""
    lines = [",".join(FIELDS)]
    for record in records:
        lines.append(
            ",".join("" if record.get(key) is None else str(record[key]) for key in FIELDS)
        )
    return "\n".join(lines) + "\n"
