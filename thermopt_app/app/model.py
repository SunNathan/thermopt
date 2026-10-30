"""Thermal model identification.

The 2R2C equations are rewritten as a second-order ARX, which makes the fit a
plain linear least squares instead of a fragile non-linear optimisation:

    T[k] = a1·T[k-1] + a2·T[k-2] + be·Te[k-1] + bp·P[k-1] + c

The second state of that ARX carries the slow, mass-like dynamic. Physical
quantities are *derived* from the coefficients and reported, but the model used
for prediction stays the identified ARX — honest and stable.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .audit import SAMPLE_HOURS

HORIZON = 48  # 12 h at 15 min
VALIDATION_STRIDE = 8
MAX_RMSE = 0.5  # °C, specification § 5.5
MIN_SAMPLES = 200


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
    ua: float | None = None
    tau_fast: float | None = None
    tau_slow: float | None = None
    gain_outdoor: float | None = None
    order_power: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "a1": self.a1,
            "a2": self.a2,
            "be": self.be,
            "bp": self.bp,
            "c": self.c,
            "rmse_12h": self.rmse_12h,
            "samples": self.samples,
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
                a2=float(data["a2"]),
                be=float(data["be"]),
                bp=float(data["bp"]),
                c=float(data["c"]),
                rmse_12h=float(data["rmse_12h"]),
                samples=int(data["samples"]),
                fitted_at=str(data["fitted_at"]),
                ua=data.get("ua"),
                tau_fast=data.get("tau_fast"),
                tau_slow=data.get("tau_slow"),
                gain_outdoor=data.get("gain_outdoor"),
                order_power={str(k): float(v) for k, v in (data.get("order_power") or {}).items()},
            )
        except (KeyError, TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Series preparation
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Series:
    """Aligned arrays ready for the regression."""

    t_air: np.ndarray
    t_ext: np.ndarray
    power: np.ndarray
    orders: list[str]

    def __len__(self) -> int:
        return len(self.t_air)


def build_series(records: Iterable[dict]) -> Series:
    """Keep only the samples where every signal is present and usable."""
    rows: list[tuple[str, float, float, float]] = []
    for record in records:
        try:
            t_air = float(record["t_air"])
            t_ext = float(record["t_ext"])
            power = float(record["power"])
        except (KeyError, TypeError, ValueError):
            continue
        order = record.get("order")
        rows.append((str(order or ""), t_air, t_ext, power))

    return Series(
        t_air=np.array([row[1] for row in rows], dtype=float),
        t_ext=np.array([row[2] for row in rows], dtype=float),
        power=np.array([row[3] for row in rows], dtype=float),
        orders=[row[0] for row in rows],
    )


def _design(series: Series, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ta, te, p = series.t_air, series.t_ext, series.power
    indices = np.arange(2, len(series))
    indices = indices[mask[2:]]
    x = np.column_stack(
        [ta[indices - 1], ta[indices - 2], te[indices - 1], p[indices - 1], np.ones(len(indices))]
    )
    return x, ta[indices]


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def fit(
    records: list[dict], *, now: datetime | None = None
) -> tuple[ModelParameters | None, list[str]]:
    """Return ``(parameters, errors)``; parameters is ``None`` when rejected."""
    series = build_series(records)
    if len(series) < MIN_SAMPLES:
        return None, [f"{len(series)} échantillons exploitables, il en faut au moins {MIN_SAMPLES}"]

    split = int(len(series) * 0.7)
    train = np.zeros(len(series), dtype=bool)
    train[:split] = True

    x, y = _design(series, train)
    if len(y) < 50:
        return None, ["pas assez d'échantillons d'apprentissage"]

    try:
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError as err:  # pragma: no cover
        return None, [f"régression impossible : {err}"]

    a1, a2, be, bp, c = (float(value) for value in coefficients)
    errors = _physical_checks(a1, a2, be, bp)
    if errors:
        return None, errors

    rmse = _free_run_rmse(series, a1, a2, be, bp, c, start=split)
    if rmse > MAX_RMSE:
        errors.append(
            f"RMSE 12 h de {rmse:.2f} °C, au-delà de la cible de {MAX_RMSE} °C : "
            "le modèle est rejeté"
        )
        return None, errors

    params = ModelParameters(
        a1=a1,
        a2=a2,
        be=be,
        bp=bp,
        c=c,
        rmse_12h=round(rmse, 3),
        samples=len(series),
        fitted_at=(now or datetime.now()).isoformat(timespec="seconds"),
        order_power=_mean_power_per_order(series),
    )
    _derive_physical(params)
    return params, []


def _physical_checks(a1: float, a2: float, be: float, bp: float) -> list[str]:
    errors: list[str] = []
    if not (-2.0 < a1 < 2.0) or not (-1.0 < a2 < 0.0):
        errors.append("coefficients autorégressifs hors du domaine physique")
    if a1 + a2 >= 1.0:
        errors.append("modèle instable (a1 + a2 ≥ 1)")
    if bp <= 0:
        errors.append("la puissance n'a pas d'effet mesurable sur la température")
    if be <= 0:
        errors.append("la température extérieure n'a pas d'effet mesurable")
    return errors


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
    """Static gain, equivalent UA and the two time constants."""
    denominator = 1.0 - params.a1 - params.a2
    if denominator > 1e-6 and params.bp > 0:
        gain = params.bp / denominator
        if gain > 0:
            params.ua = round(1.0 / gain, 1)
        if params.be > 0:
            params.gain_outdoor = round(params.be / denominator, 2)

    params.tau_fast, params.tau_slow = _time_constants(params.a1, params.a2)


def _time_constants(a1: float, a2: float) -> tuple[float | None, float | None]:
    """Roots of z² − a1·z − a2 = 0, converted to hours."""
    discriminant = a1 * a1 + 4.0 * a2
    if discriminant < 0:
        return None, None
    root = math.sqrt(discriminant)
    poles = [(a1 + root) / 2.0, (a1 - root) / 2.0]
    taus: list[float] = []
    for pole in poles:
        if 0 < pole < 1:
            taus.append(-SAMPLE_HOURS / math.log(pole))
    if len(taus) != 2:
        return None, None
    return round(min(taus), 2), round(max(taus), 2)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
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
        ta = params.a1 * ta1 + params.a2 * ta2 + params.be * te + params.bp * pw + params.c
        out.append(ta)
        ta2, ta1 = ta1, ta
    return out


def _free_run_rmse(
    series: Series,
    a1: float,
    a2: float,
    be: float,
    bp: float,
    c: float,
    *,
    start: int,
    horizon: int = HORIZON,
) -> float:
    """Average error of a 12 h free-run, over the validation window."""
    params = ModelParameters(a1=a1, a2=a2, be=be, bp=bp, c=c, rmse_12h=0.0, samples=0, fitted_at="")
    ta = series.t_air
    errors: list[float] = []

    index = max(2, start)
    while index + horizon < len(series):
        predicted = simulate(
            params,
            ta_prev2=float(ta[index - 2]),
            ta_prev1=float(ta[index - 1]),
            # The regression predicts T[k] from the inputs at k-1.
            t_ext=[float(v) for v in series.t_ext[index - 1 : index - 1 + horizon]],
            power=[float(v) for v in series.power[index - 1 : index - 1 + horizon]],
        )
        actual = ta[index : index + horizon]
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
    predicted = simulate(
        params,
        ta_prev2=float(series.t_air[-2]),
        ta_prev1=float(series.t_air[-1]),
        t_ext=[t_ext] * steps,
        power=[power_w] * steps,
    )
    return round(predicted[-1], 1) if predicted else None
