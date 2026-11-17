"""Thermal model identification.

Two structures are attempted, because a room held at a constant setpoint has
very little excitation: the second-order ARX is then ill-conditioned and can
produce coefficients at the edge of stability. The first-order ARX is much
better conditioned and often wins on real data.

    ARX(2): T[k] = a1·T[k-1] + a2·T[k-2] + be·Te[k-1] + bp·P[k-1] + c
    ARX(1): T[k] = a1·T[k-1]             + be·Te[k-1] + bp·P[k-1] + c

The series is cut into contiguous segments: a gap would make the recursion
compare temperatures hours apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

HORIZON = 48  # 12 h at 15 min
VALIDATION_STRIDE = 8
MAX_RMSE = 0.5  # °C, specification § 5.5
MIN_SAMPLES = 200
STEP_MINUTES = 15
STEP_HOURS = STEP_MINUTES / 60
STEP_SECONDS = STEP_MINUTES * 60
GAP_FACTOR = 1.5
EXCITATION_WEIGHT = 3.0
EXCITATION_POWER = 50.0  # W
EXCITATION_DELTA_T = 0.15  # K

STRUCTURES = ("arx2", "arx1")


@dataclass(slots=True)
class ModelParameters:
    """Identified model, plus the numbers that make it interpretable."""

    a1: float
    a2: float
    be: float
    bp: float
    c: float
    rmse_12h: float
    samples: int
    fitted_at: str
    structure: str = "arx2"
    segments: int = 0
    ua: float | None = None
    tau_fast: float | None = None
    tau_slow: float | None = None
    gain_outdoor: float | None = None
    order_power: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "structure": self.structure,
            "a1": self.a1,
            "a2": self.a2,
            "be": self.be,
            "bp": self.bp,
            "c": self.c,
            "rmse_12h": self.rmse_12h,
            "samples": self.samples,
            "segments": self.segments,
            "fitted_at": self.fitted_at,
            "ua": self.ua,
            "tau_fast": self.tau_fast,
            "tau_slow": self.tau_slow,
            "gain_outdoor": self.gain_outdoor,
            "order_power": self.order_power,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> ModelParameters | None:
        if not data:
            return None
        try:
            return cls(
                a1=float(data["a1"]),
                a2=float(data.get("a2", 0.0)),
                be=float(data["be"]),
                bp=float(data["bp"]),
                c=float(data["c"]),
                rmse_12h=float(data["rmse_12h"]),
                samples=int(data["samples"]),
                fitted_at=str(data["fitted_at"]),
                structure=str(data.get("structure", "arx2")),
                segments=int(data.get("segments", 0)),
                ua=data.get("ua"),
                tau_fast=data.get("tau_fast"),
                tau_slow=data.get("tau_slow"),
                gain_outdoor=data.get("gain_outdoor"),
                order_power={str(k): float(v) for k, v in (data.get("order_power") or {}).items()},
            )
        except (KeyError, TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Series:
    """Aligned arrays, split into contiguous segments."""

    t_air: np.ndarray
    t_ext: np.ndarray
    power: np.ndarray
    orders: list[str]
    segments: list[tuple[int, int]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.t_air)

    @property
    def segment_count(self) -> int:
        return max(1, len(self.segments))


def _epoch(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def build_series(records: list[dict]) -> Series:
    """Keep usable samples, sort them, and cut on gaps."""
    rows: list[tuple[float, str, float, float, float]] = []
    for record in records:
        stamp = _epoch(record.get("ts"))
        if stamp is None:
            continue
        try:
            t_air = float(record["t_air"])
            t_ext = float(record["t_ext"])
            power = float(record["power"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((stamp, str(record.get("order") or ""), t_air, t_ext, power))

    rows.sort(key=lambda row: row[0])

    segments: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(rows)):
        if rows[index][0] - rows[index - 1][0] > GAP_FACTOR * STEP_SECONDS:
            segments.append((start, index))
            start = index
    if rows:
        segments.append((start, len(rows)))

    return Series(
        t_air=np.array([row[2] for row in rows], dtype=float),
        t_ext=np.array([row[3] for row in rows], dtype=float),
        power=np.array([row[4] for row in rows], dtype=float),
        orders=[row[1] for row in rows],
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
def step(
    params: ModelParameters, t_prev2: float, t_prev1: float, t_ext: float, power: float
) -> float:
    """One prediction step, for either structure."""
    if params.structure == "arx1":
        return params.a1 * t_prev1 + params.be * t_ext + params.bp * power + params.c
    return (
        params.a1 * t_prev1 + params.a2 * t_prev2 + params.be * t_ext + params.bp * power + params.c
    )


def simulate(
    params: ModelParameters,
    ta_prev2: float,
    ta_prev1: float,
    t_ext: list[float],
    power: list[float],
) -> list[float]:
    """Free-run simulation, one step per element of ``t_ext``/``power``."""
    ta2, ta1 = ta_prev2, ta_prev1
    out: list[float] = []
    for te, pw in zip(t_ext, power, strict=False):
        value = step(params, ta2, ta1, te, pw)
        out.append(value)
        ta2, ta1 = ta1, value
    return out


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def _design(series: Series, structure: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rows, targets and weights, built segment by segment."""
    lag = 2 if structure == "arx2" else 1
    rows: list[list[float]] = []
    targets: list[float] = []
    weights: list[float] = []

    ta, te, p = series.t_air, series.t_ext, series.power
    for start, end in series.segments:
        for index in range(start + lag, end):
            if structure == "arx2":
                features = [ta[index - 1], ta[index - 2], te[index - 1], p[index - 1], 1.0]
            else:
                features = [ta[index - 1], te[index - 1], p[index - 1], 1.0]
            rows.append(features)
            targets.append(ta[index])

            moved = abs(p[index - 1] - p[index - 2]) > EXCITATION_POWER
            changed = abs(ta[index] - ta[index - 1]) > EXCITATION_DELTA_T
            weights.append(EXCITATION_WEIGHT if (moved or changed) else 1.0)

    return (
        np.array(rows, dtype=float),
        np.array(targets, dtype=float),
        np.array(weights, dtype=float),
    )


def _physical_checks(structure: str, coefficients: np.ndarray) -> list[str]:
    errors: list[str] = []
    if structure == "arx2":
        a1, a2, be, bp = (float(value) for value in coefficients[:4])
        if not (-2.0 < a1 < 2.0) or not (-1.0 < a2 < 0.0):
            errors.append(
                f"ARX2 : coefficients autorégressifs hors du domaine physique (a1={a1:.3f}, a2={a2:.3f})"
            )
        if a1 + a2 >= 1.0:
            errors.append(f"ARX2 : modèle instable (a1+a2={a1 + a2:.3f} ≥ 1)")
    else:
        a1, be, bp = (float(value) for value in coefficients[:3])
        if not (0.0 < a1 < 1.0):
            errors.append(
                f"ARX1 : coefficient autorégressif hors du domaine physique (a1={a1:.3f})"
            )

    be = float(coefficients[2] if structure == "arx2" else coefficients[1])
    bp = float(coefficients[3] if structure == "arx2" else coefficients[2])
    if bp <= 0:
        errors.append(f"{structure.upper()} : la puissance n'a pas d'effet mesurable (bp={bp:.6f})")
    if be <= 0:
        errors.append(f"{structure.upper()} : la température extérieure n'a pas d'effet mesurable")
    return errors


def _fit_structure(series: Series, structure: str) -> tuple[ModelParameters | None, list[str]]:
    x, y, w = _design(series, structure)
    if len(y) < 50:
        return None, [f"{structure.upper()} : {len(y)} équations, trop peu pour ajuster"]

    try:
        coefficients, *_ = np.linalg.lstsq(x * w[:, None], y * w, rcond=None)
    except np.linalg.LinAlgError as err:  # pragma: no cover
        return None, [f"{structure.upper()} : régression impossible ({err})"]

    errors = _physical_checks(structure, coefficients)
    if errors:
        return None, errors

    if structure == "arx2":
        a1, a2, be, bp, c = (float(value) for value in coefficients)
    else:
        a1, be, bp, c = (float(value) for value in coefficients)
        a2 = 0.0

    params = ModelParameters(
        a1=a1,
        a2=a2,
        be=be,
        bp=bp,
        c=c,
        rmse_12h=0.0,
        samples=len(series),
        fitted_at="",
        structure=structure,
        segments=series.segment_count,
    )
    params.rmse_12h = round(_free_run_rmse(series, params), 3)
    _derive_physical(params)
    return params, []


def fit(
    records: list[dict], *, now: datetime | None = None
) -> tuple[ModelParameters | None, list[str]]:
    """Return ``(parameters, errors)``; parameters is ``None`` when rejected."""
    series = build_series(records)
    if len(series) < MIN_SAMPLES:
        return None, [f"{len(series)} échantillons exploitables, il en faut au moins {MIN_SAMPLES}"]

    attempts: list[ModelParameters] = []
    errors: list[str] = []
    for structure in STRUCTURES:
        params, problems = _fit_structure(series, structure)
        if params is None:
            errors.extend(problems)
        else:
            attempts.append(params)

    if not attempts:
        return None, errors

    best = min(attempts, key=lambda item: item.rmse_12h)
    if best.rmse_12h > MAX_RMSE:
        errors.append(
            f"{best.structure.upper()} : RMSE 12 h de {best.rmse_12h:.2f} °C, au-delà de "
            f"la cible de {MAX_RMSE} °C sur {best.samples} échantillons "
            f"en {best.segments} segment(s)"
        )
        return None, errors

    best.fitted_at = (now or datetime.now()).isoformat(timespec="seconds")
    best.order_power = _mean_power_per_order(series)
    return best, []


def _mean_power_per_order(series: Series) -> dict[str, float]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for order, power in zip(series.orders, series.power, strict=True):
        if not order:
            continue
        totals[order] = totals.get(order, 0.0) + float(power)
        counts[order] = counts.get(order, 0) + 1
    return {order: round(totals[order] / counts[order], 1) for order in totals if counts[order]}


def _derive_physical(params: ModelParameters) -> None:
    """Static gain, equivalent UA and the time constants."""
    denominator = 1.0 - params.a1 - (params.a2 if params.structure == "arx2" else 0.0)
    if denominator > 1e-6 and params.bp > 0:
        gain = params.bp / denominator
        if gain > 0:
            params.ua = round(1.0 / gain, 1)
        if params.be > 0:
            params.gain_outdoor = round(params.be / denominator, 2)

    if params.structure == "arx1":
        tau = _tau(params.a1)
        params.tau_fast = tau
        params.tau_slow = tau
        return

    params.tau_fast, params.tau_slow = _time_constants(params.a1, params.a2)


def _tau(pole: float) -> float | None:
    if not 0 < pole < 1:
        return None
    return round(-STEP_HOURS / math.log(pole), 2)


def _time_constants(a1: float, a2: float) -> tuple[float | None, float | None]:
    """Roots of z² − a1·z − a2 = 0, converted to hours."""
    discriminant = a1 * a1 + 4.0 * a2
    if discriminant < 0:
        return None, None
    root = math.sqrt(discriminant)
    taus = [tau for tau in (_tau((a1 + root) / 2.0), _tau((a1 - root) / 2.0)) if tau]
    if len(taus) != 2:
        return None, None
    return min(taus), max(taus)


def _free_run_rmse(series: Series, params: ModelParameters) -> float:
    """Average error of a 12 h free-run, computed inside each segment."""
    lag = 2 if params.structure == "arx2" else 1
    ta = series.t_air
    errors: list[float] = []

    for start, end in series.segments:
        index = start + lag
        while index + HORIZON <= end:
            predicted = simulate(
                params,
                ta_prev2=float(ta[index - 2]) if lag == 2 else float(ta[index - 1]),
                ta_prev1=float(ta[index - 1]),
                # The regression predicts T[k] from the inputs at k-1.
                t_ext=[float(v) for v in series.t_ext[index - 1 : index - 1 + HORIZON]],
                power=[float(v) for v in series.power[index - 1 : index - 1 + HORIZON]],
            )
            actual = ta[index : index + HORIZON]
            errors.extend((np.array(predicted) - actual).tolist())
            index += VALIDATION_STRIDE

    if not errors:
        return float("inf")
    return float(np.sqrt(np.mean(np.square(errors))))


def predict(
    params: ModelParameters,
    history: list[dict],
    power_w: float,
    steps: int = HORIZON,
) -> float | None:
    """Temperature after ``steps`` samples, assuming constant power and weather."""
    series = build_series(history)
    if len(series) < 2:
        return None
    t_ext = float(series.t_ext[-1])
    lag = 2 if params.structure == "arx2" else 1
    if len(series) < lag + 1:
        return None
    predicted = simulate(
        params,
        ta_prev2=float(series.t_air[-2]),
        ta_prev1=float(series.t_air[-1]),
        t_ext=[t_ext] * steps,
        power=[power_w] * steps,
    )
    return round(predicted[-1], 1) if predicted else None
