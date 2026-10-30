"""Tests for the MPC planner."""

from __future__ import annotations

from datetime import datetime

from app.model import ModelParameters
from app.mpc import (
    DT_HOURS,
    HARD_FLOOR,
    MIN_INTERVAL_STEPS,
    STEPS,
    build_plan,
    evaluate_orders,
    power_for,
)
from thermopt_lib.core.orders import Ladder, Order

START = datetime(2026, 1, 5, 0, 0)
LADDER = Ladder(comfort=20.5, frost=7.0)
P_MAX = 1200.0

PARAMS = ModelParameters(
    a1=1.55,
    a2=-0.6,
    be=0.045,
    bp=0.0006,
    c=0.35,
    rmse_12h=0.2,
    samples=1000,
    fitted_at="2026-01-01",
    ua=100.0,
    tau_fast=1.0,
    tau_slow=1.2,
    gain_outdoor=1.0,
    order_power={"comfort": 900.0, "eco": 200.0},
)


def _setup(price_hp: float = 0.20, price_hc: float = 0.12, tmin: float = 19.5):
    # HC for the first 6 h, then HP.
    prices = [price_hc] * 24 + [price_hp] * (STEPS - 24)
    return {
        "params": PARAMS,
        "ladder": LADDER,
        "t_min": [tmin] * STEPS,
        "prices": prices,
        "t_ext": [5.0] * STEPS,
        "t_now": 19.0,
        "t_prev": 19.0,
        "p_max": P_MAX,
        "start": START,
    }


def test_power_is_a_saturation_on_the_setpoint() -> None:
    assert power_for(Order.COMFORT, 10.0, LADDER, P_MAX) == P_MAX
    assert power_for(Order.COMFORT, 20.5, LADDER, P_MAX) == 0.0
    assert power_for(Order.COMFORT, 25.0, LADDER, P_MAX) == 0.0
    middle = power_for(Order.COMFORT, 20.25, LADDER, P_MAX)
    assert 0.0 < middle < P_MAX


def test_colder_order_delivers_less_at_the_same_temperature() -> None:
    comfort = power_for(Order.COMFORT, 18.0, LADDER, P_MAX)
    eco = power_for(Order.ECO, 18.0, LADDER, P_MAX)
    assert comfort > eco


def test_plan_respects_the_change_interval() -> None:
    plan = build_plan(**_setup())

    orders = [step.order for step in plan.steps]
    for index in range(1, len(orders)):
        if orders[index] is not orders[index - 1]:
            # A change is only legal after the minimum interval.
            assert index >= MIN_INTERVAL_STEPS
            assert orders[index - MIN_INTERVAL_STEPS : index].count(orders[index]) == 0


def test_plan_never_goes_below_the_frost_floor() -> None:
    plan = build_plan(**_setup(tmin=19.5))
    assert plan.min_temp >= HARD_FLOOR
    assert plan.feasible


def test_plan_keeps_the_room_within_comfort() -> None:
    plan = build_plan(**_setup())
    # Tolerance of the planner: comfort is soft (λ), but the deviation must stay small.
    assert min(step.t_pred for step in plan.steps) >= 18.5


def test_plan_is_cheaper_than_always_comfort() -> None:
    setup = _setup()
    plan = build_plan(**setup)

    naive_cost, _penalty, _temps = evaluate_orders(
        **{k: v for k, v in setup.items() if k != "start"},
        orders=[Order.COMFORT] * STEPS,
    )

    assert plan.cost < naive_cost


def test_plan_preheats_before_the_peak_switch() -> None:
    """Cheap hours end at 06:00, occupancy starts at 07:00.

    The plan must store heat during the cheap hours instead of paying for it
    during the peak.
    """
    setup = _setup()
    setup["t_min"] = [17.0] * 28 + [19.5] * (STEPS - 28)

    plan = build_plan(**setup)

    before = [step.t_pred for step in plan.steps[18:24]]
    at_occupancy = plan.steps[28].t_pred

    assert max(before) > 18.0, before
    assert at_occupancy >= 19.0, at_occupancy
    assert any(step.order is Order.COMFORT for step in plan.steps[16:24])


def test_plan_shape() -> None:
    plan = build_plan(**_setup())

    assert len(plan.steps) == STEPS
    assert plan.steps[0].moment == START
    assert plan.steps[1].moment.minute == 15
    assert plan.changes >= 0
    assert plan.evaluations > 0
    assert len(plan.hourly()) == 24


def test_hourly_summary_matches_the_plan() -> None:
    plan = build_plan(**_setup())
    hourly = plan.hourly()

    assert hourly[0].moment == plan.steps[0].moment
    assert hourly[1].moment.hour == plan.steps[0].moment.hour + 1


def test_every_step_has_a_cost() -> None:
    plan = build_plan(**_setup())

    total = sum(step.cost for step in plan.steps[:8])
    assert abs(total - plan.cost) > 0  # cost covers the whole horizon
    assert all(step.cost >= 0 for step in plan.steps)
    assert DT_HOURS == 0.25
