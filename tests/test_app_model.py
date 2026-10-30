"""Tests for the audit and the thermal model identification."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from app.audit import MIN_DAYS, audit
from app.model import build_series, fit, predict, simulate

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
