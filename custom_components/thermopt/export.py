"""CSV export of the internal sampling buffer.

The recorder is purged after ``purge_keep_days`` (10 days by default) and the
pilot wire order is not stored in long-term statistics, so this buffer is the
only place where order and power are aligned. Exporting it is the prerequisite
for offline identification.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .runtime import ThermOptRuntime

_LOGGER = logging.getLogger(__name__)

HEADER = ("timestamp", "piece", "t_air", "humidite", "puissance", "energie", "ordre")
EXPORT_DIR = "thermopt_exports"


def export_csv(hass: HomeAssistant, runtime: ThermOptRuntime) -> tuple[Path, int]:
    """Write every room buffer to one CSV file. Blocking: run in an executor."""
    directory = Path(hass.config.path(EXPORT_DIR))
    directory.mkdir(parents=True, exist_ok=True)

    stamp = dt_util.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"thermopt_{stamp}.csv"

    rows = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(HEADER)

        for room in runtime.rooms.values():
            series = room.series
            name = room.config.name
            for index, timestamp in enumerate(series.ts):
                writer.writerow(
                    (
                        datetime.fromtimestamp(timestamp)
                        .astimezone()
                        .isoformat(timespec="seconds"),
                        name,
                        series.columns["t_air"][index],
                        series.columns["humidity"][index],
                        series.columns["power"][index],
                        series.columns["energy"][index],
                        series.columns["order"][index],
                    )
                )
                rows += 1

    _LOGGER.info("Exported %s samples to %s", rows, path)
    return path, rows
