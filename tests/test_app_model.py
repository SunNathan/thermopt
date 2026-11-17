"""Tests for the audit and the thermal model identification."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from app.audit import MIN_DAYS, audit
from app.model import ModelParameters, build_series, fit, predict, simulate, step

START = datetime(2026, 1, 1, 0, 0)
STEP = timedelta(minutes=15)
ORDER_POWER = {"comfort": 900.0, "comfort_1": 400.0, "eco": 0.0}


def _records(days: int = 20, *, seed: int = 7, orders: bool = True) -> list[dict]:
    """Synthetic history produced by a known ARX model."""
    rng = np.random.default_rng(seed)
    a1, a2, be, bp, c = 1.55, -0.6, 0.045, 0.0006, 0.35

    steps = days * 96
    t_ext = 8.0 + 3.0 * np.sin(np.linspace(0, days * 2 * np.pi, steps)) + rng.normal(0, 0.2, steps)

    names = list(ORDER_POWER) if orders else ["eco"]
    series_orders: list[str] = []
    power = np.zeros(steps)
    for index in range(steps):
        order = names[(index // 12) % len(names)]  # change every 3 h
        series_orders.append(order)
        power[index] = ORDER_POWER[order]

    t_air = np.zeros(steps)
    t_air[0] = t_air[1] = 19.0
    for k in range(2, steps):
        t_air[k] = (
            a1 * t_air[k - 1]
            + a2 * t_air[k - 2]
            + be * t_ext[k - 1]
            + bp * power[k - 1]
            + c
            + rng.normal(0, 0.01)
        )

    records = []
    for k in range(steps):
        records.append(
            {
                "ts": (START + k * STEP).isoformat(timespec="seconds"),
                "room": "Salon",
                "t_air": round(float(t_air[k]), 3),
                "t_ext": round(float(t_ext[k]), 3),
                "order": series_orders[k],
                "power": float(power[k]),
                "energy": None,
                "target_min": 19.5,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def test_audit_accepts_a_rich_history() -> None:
    report = audit(_records(20), "Salon")

    assert report.samples == 20 * 96
    assert report.days >= MIN_DAYS
    assert report.cooling_episodes > 0
    assert report.ok, report.missing
    assert set(report.hours_per_order) == {"comfort", "comfort_1", "eco"}


def test_audit_rejects_a_short_history() -> None:
    report = audit(_records(3), "Salon")
    assert not report.ok
    assert any("jour(s) de données" in item for item in report.missing)


def test_audit_rejects_a_single_order() -> None:
    report = audit(_records(20, orders=False), "Salon")
    assert not report.ok
    assert any("ordres" in item for item in report.missing)


def test_audit_reports_empty_history() -> None:
    report = audit([], "Salon")
    assert report.samples == 0
    assert report.missing == ["aucune donnée collectée"]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def test_build_series_drops_incomplete_records() -> None:
    records = _records(1)
    records.append({"ts": START.isoformat(), "room": "Salon", "t_air": None})
    series = build_series(records)
    assert len(series) == len(records) - 1


def test_fit_recovers_the_generating_model() -> None:
    params, errors = fit(_records(20))

    assert errors == [], errors
    assert params is not None
    assert abs(params.a1 - 1.55) < 0.12
    assert abs(params.a2 + 0.6) < 0.12
    assert abs(params.bp - 0.0006) < 0.0004
    assert params.rmse_12h <= 0.5


def test_fit_derives_interpretable_numbers() -> None:
    params, _errors = fit(_records(20))
    assert params is not None
    assert params.ua is not None and 20 < params.ua < 2000
    assert params.tau_fast is not None and params.tau_slow is not None
    assert params.tau_slow >= params.tau_fast > 0


def test_fit_rejects_short_history() -> None:
    params, errors = fit(_records(1))
    assert params is None
    assert errors


def test_fit_rejects_no_power_variation() -> None:
    params, errors = fit(_records(20, orders=False))
    assert params is None
    assert errors


def test_simulate_is_stable() -> None:
    params, _errors = fit(_records(20))
    assert params is not None

    values = simulate(params, 19.0, 19.0, [8.0] * 48, [0.0] * 48)
    assert len(values) == 48
    assert all(np.isfinite(values))
    assert values[-1] < 19.0  # cooling towards the outside


def test_predict_under_constant_power() -> None:
    records = _records(20)
    params, _errors = fit(records)
    assert params is not None

    hot = predict(params, records[-200:], power_w=1500.0)
    cold = predict(params, records[-200:], power_w=0.0)

    assert hot is not None and cold is not None
    assert hot > cold


def test_parameters_roundtrip() -> None:
    params, _errors = fit(_records(20))
    assert params is not None

    from app.model import ModelParameters

    restored = ModelParameters.from_dict(params.to_dict())
    assert restored is not None
    assert restored.a1 == params.a1
    assert restored.order_power == params.order_power


# ---------------------------------------------------------------------------
# Robustness: gaps, structures, weighting
# ---------------------------------------------------------------------------
def _arx1_records(days: int = 20, seed: int = 3) -> list[dict]:
    """A first-order process: the second order has nothing to learn."""
    rng = np.random.default_rng(seed)
    steps = days * 96
    t_ext = 7.0 + rng.normal(0, 0.4, steps)
    power = np.zeros(steps)
    orders: list[str] = []
    for index in range(steps):
        order = "comfort" if (index // 8) % 2 == 0 else "eco"
        orders.append(order)
        power[index] = 900.0 if order == "comfort" else 0.0

    t_air = np.zeros(steps)
    t_air[0] = 19.0
    for k in range(1, steps):
        t_air[k] = 0.96 * t_air[k - 1] + 0.03 * t_ext[k - 1] + 0.0004 * power[k - 1] + 0.15
        t_air[k] += rng.normal(0, 0.01)

    return [
        {
            "ts": (START + k * STEP).isoformat(timespec="seconds"),
            "room": "Salon",
            "t_air": round(float(t_air[k]), 3),
            "t_ext": round(float(t_ext[k]), 3),
            "order": orders[k],
            "power": float(power[k]),
            "energy": None,
            "target_min": 19.5,
        }
        for k in range(steps)
    ]


def test_gaps_split_the_series_into_segments() -> None:
    records = _records(20)
    # remove a 3 h chunk in the middle
    holed = records[:500] + records[512:]
    series = build_series(holed)

    assert len(series) == len(holed)
    assert len(series.segments) == 2
    assert series.segments[0] == (0, 500)
    assert series.segments[1] == (500, len(holed))


def test_fit_ignores_segment_boundaries() -> None:
    """A gap must not be crossed by the regression."""
    records = _records(20)
    holed = records[:900] + records[1200:]
    params, errors = fit(holed)

    assert params is not None, errors
    assert params.segments == 2


def test_first_order_process_selects_the_first_order_model() -> None:
    params, errors = fit(_arx1_records(20))

    assert params is not None, errors
    assert params.structure == "arx1"
    assert 0 < params.a1 < 1
    assert params.rmse_12h <= 0.5


def test_step_handles_both_structures() -> None:
    arx2 = ModelParameters(
        a1=1.5, a2=-0.55, be=0.05, bp=0.0005, c=0.2, rmse_12h=0.1, samples=10, fitted_at=""
    )
    arx1 = ModelParameters(
        a1=0.97,
        a2=0.0,
        be=0.03,
        bp=0.0004,
        c=0.1,
        rmse_12h=0.1,
        samples=10,
        fitted_at="",
        structure="arx1",
    )

    assert step(arx2, 19.0, 19.5, 8.0, 500.0) == pytest.approx(
        1.5 * 19.5 - 0.55 * 19.0 + 0.05 * 8.0 + 0.0005 * 500.0 + 0.2
    )
    assert step(arx1, 19.0, 19.5, 8.0, 500.0) == pytest.approx(
        0.97 * 19.5 + 0.03 * 8.0 + 0.0004 * 500.0 + 0.1
    )


def test_parameters_roundtrip_keeps_the_structure() -> None:
    params, _errors = fit(_arx1_records(20))
    assert params is not None

    restored = ModelParameters.from_dict(params.to_dict())
    assert restored is not None
    assert restored.structure == params.structure
    assert restored.segments == params.segments
