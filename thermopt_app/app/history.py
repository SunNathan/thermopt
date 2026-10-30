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
import shutil
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_ROOT = Path("/data/history")
RETENTION_MONTHS = 2  # current month plus the two previous ones
DISK_MIN_FREE = 200 * 1024 * 1024  # 200 MB
FIELDS = ("ts", "room", "t_air", "t_ext", "order", "power", "energy", "target_min")


def month_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


class HistoryStore:
    """Read and append the monthly files."""

    def __init__(self, root: Path = DEFAULT_ROOT) -> None:
        self.root = root
        self.free_bytes: int | None = None
        self.last_error: str | None = None
        self.removed: list[str] = []

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
                self.last_error = str(err)
        return count

    async def async_append(self, records: Iterable[dict[str, Any]]) -> int:
        return await asyncio.to_thread(self.append, list(records))

    # -- reading -------------------------------------------------------------
    def read(
        self,
        *,
        room: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict]:
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
                        if since is not None or until is not None:
                            stamp = _parse(record.get("ts"))
                            if stamp is None:
                                continue
                            if since is not None and stamp < since:
                                continue
                            if until is not None and stamp > until:
                                continue
                        records.append(record)
            except OSError as err:  # pragma: no cover
                _LOGGER.warning("Lecture impossible de %s : %s", path, err)

        records.sort(key=lambda item: str(item.get("ts")))
        return records

    async def async_read(
        self,
        *,
        room: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ):
        return await asyncio.to_thread(self.read, room=room, since=since, until=until)

    def size(self) -> int:
        return sum(path.stat().st_size for path in self.files() if path.exists())

    # -- housekeeping --------------------------------------------------------
    def prune(self, keep: int = RETENTION_MONTHS, now: datetime | None = None) -> list[str]:
        """Delete monthly files older than ``keep`` months.

        With ``keep=2`` in November, September, October and November survive.
        """
        reference = now or datetime.now()
        cutoff = reference.year * 12 + reference.month - keep
        removed: list[str] = []

        for path in self.files():
            try:
                year, month = (int(part) for part in path.stem.split("-"))
            except ValueError:
                continue
            if year * 12 + month < cutoff:
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError as err:  # pragma: no cover
                    _LOGGER.warning("Purge impossible de %s : %s", path, err)

        self.removed = removed
        if removed:
            _LOGGER.info("Historique purgé : %s", ", ".join(removed))
        return removed

    def refresh_disk(self) -> int | None:
        """Free space of the volume holding the history, in bytes."""
        probe = self.root if self.root.exists() else self.root.parent
        try:
            self.free_bytes = shutil.disk_usage(probe).free
        except OSError as err:  # pragma: no cover
            _LOGGER.warning("Espace disque illisible : %s", err)
            self.free_bytes = None
        return self.free_bytes

    def low_disk(self, minimum: int = DISK_MIN_FREE) -> bool:
        if self.free_bytes is None:
            self.refresh_disk()
        return self.free_bytes is not None and self.free_bytes < minimum

    def file_range(self) -> tuple[str, str] | None:
        """First and last month available, from the filenames only."""
        names = [path.stem for path in self.files()]
        if not names:
            return None
        return min(names), max(names)


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
