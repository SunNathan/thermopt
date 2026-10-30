"""Is the collected history enough to identify a thermal model?

Pure Python: the answer must be computable, and testable, without Home
Assistant. The thresholds come from the specification (§ 5.5 and the phase 2
excitation phase).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SAMPLE_MINUTES = 15
SAMPLE_HOURS = SAMPLE_MINUTES / 60

MIN_DAYS = 14
MIN_HOURS_PER_ORDER = 20
MIN_ORDERS = 2
MIN_COOLING_EPISODES = 10
COOLING_MIN_HOURS = 3
COOLING_MAX_POWER = 20.0
GAP_MINUTES = 45


@dataclass(slots=True)
class AuditReport:
    """What the history contains, and whether it is usable."""

    room: str
    samples: int = 0
    days: float = 0.0
    first: datetime | None = None
    last: datetime | None = None
    gaps: int = 0
    hours_per_order: dict[str, float] = field(default_factory=dict)
    mean_power_per_order: dict[str, float] = field(default_factory=dict)
    cooling_episodes: int = 0
    cooling_hours: float = 0.0
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def audit(records: list[dict], room: str) -> AuditReport:
    """Analyse one room's records (already filtered) and explain what is missing."""
    report = AuditReport(room=room)

    rows = []
    for record in records:
        stamp = _parse(record.get("ts"))
        if stamp is None:
            continue
        rows.append((stamp, record))
    rows.sort(key=lambda item: item[0])

    report.samples = len(rows)
    if not rows:
        report.missing.append("aucune donnée collectée")
        return report

    report.first = rows[0][0]
    report.last = rows[-1][0]
    report.days = round((report.last - report.first).total_seconds() / 86400, 1)

    previous: datetime | None = None
    for stamp, _record in rows:
        if previous is not None and (stamp - previous).total_seconds() > GAP_MINUTES * 60:
            report.gaps += 1
        previous = stamp

    # Hours and mean power per order.
    power_sum: dict[str, float] = {}
    power_count: dict[str, int] = {}
    for _stamp, record in rows:
        order = record.get("order")
        if not isinstance(order, str) or not order:
            continue
        report.hours_per_order[order] = round(
            report.hours_per_order.get(order, 0.0) + SAMPLE_HOURS, 2
        )
        power = _number(record.get("power"))
        if power is not None:
            power_sum[order] = power_sum.get(order, 0.0) + power
            power_count[order] = power_count.get(order, 0) + 1

    for order, total in power_sum.items():
        count = power_count.get(order, 0)
        if count:
            report.mean_power_per_order[order] = round(total / count, 1)

    # Free-cooling episodes: long stretches with no heating power.
    run_start: datetime | None = None
    run_hours = 0.0
    for stamp, record in rows:
        power = _number(record.get("power"))
        idle = power is not None and power <= COOLING_MAX_POWER
        if not idle:
            _close_cooling(report, run_start, run_hours)
            run_start, run_hours = None, 0.0
            continue
        if run_start is None:
            run_start = stamp
        run_hours += SAMPLE_HOURS
    _close_cooling(report, run_start, run_hours)

    # -- verdict -------------------------------------------------------------
    if report.days < MIN_DAYS:
        report.missing.append(f"{report.days} jour(s) de données, il en faut au moins {MIN_DAYS}")

    usable_orders = {
        order
        for order, hours in report.hours_per_order.items()
        if hours >= MIN_HOURS_PER_ORDER and order != "frost"
    }
    if len(usable_orders) < MIN_ORDERS:
        report.missing.append(
            "au moins {} ordres doivent être utilisés {}+ heures chacun (actuellement : {})".format(
                MIN_ORDERS,
                MIN_HOURS_PER_ORDER,
                ", ".join(
                    f"{order} {hours:.0f} h"
                    for order, hours in sorted(report.hours_per_order.items())
                )
                or "aucun",
            )
        )

    if report.cooling_episodes < MIN_COOLING_EPISODES:
        report.missing.append(
            f"{report.cooling_episodes} période(s) de refroidissement de "
            f"{COOLING_MIN_HOURS} h ou plus, il en faut {MIN_COOLING_EPISODES}"
        )

    if report.gaps > max(4, report.days):
        report.missing.append(
            f"{report.gaps} trou(s) de plus de {GAP_MINUTES} min : la série est trop discontinue"
        )

    return report


def _close_cooling(report: AuditReport, start: datetime | None, hours: float) -> None:
    if start is not None and hours >= COOLING_MIN_HOURS:
        report.cooling_episodes += 1
        report.cooling_hours = round(report.cooling_hours + hours, 1)
