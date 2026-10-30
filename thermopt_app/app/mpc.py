"""Model Predictive Control: pick the cheapest 24 h sequence of fil pilote orders.

Pure Python. The model is the identified ARX; the power delivered by an order is
a saturation on that order's setpoint, which is what a thermostat actually does:

    P(order, T) = P_max · clamp((consigne(order) − T) / bande, 0, 1)

Search: greedy construction, then hill-climbing on 1–2 h blocks, with a bounded
number of model evaluations so the cycle stays cheap on a Raspberry Pi.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from thermopt_lib.core.orders import ACTIVE_ORDERS, Ladder, Order

from .model import ModelParameters

STEPS = 96
DT_HOURS = 0.25
DEFAULT_BAND = 0.5
DEFAULT_LAMBDA = 1.0
MIN_INTERVAL_STEPS = 2  # one change per 30 minutes
LOOKAHEAD = 8  # 2 h
BUDGET = 1000
HARD_FLOOR = 7.0
INFEASIBLE_PENALTY = 500.0
SEED = 42


@dataclass(frozen=True, slots=True)
class Step:
    """One decision in the plan."""

    moment: datetime
    order: Order
    t_pred: float
    price: float
    power: float
    cost: float


@dataclass(frozen=True, slots=True)
class Plan:
    """Result of the optimisation."""

    steps: tuple[Step, ...]
    cost: float
    penalty: float
    changes: int
    min_temp: float
    feasible: bool
    evaluations: int

    @property
    def next_order(self) -> Order | None:
        return self.steps[0].order if self.steps else None

    def hourly(self) -> list[Step]:
        """One representative step per hour, for the interface."""
        return list(self.steps[::4])


def power_for(
    order: Order, t_air: float, ladder: Ladder, p_max: float, band: float = DEFAULT_BAND
) -> float:
    """Power the radiator delivers under ``order`` at temperature ``t_air``."""
    consigne = ladder.setpoint(order)
    ratio = (consigne - t_air) / band
    return max(0.0, min(1.0, ratio)) * p_max


def _repair(orders: list[Order]) -> list[Order]:
    """Enforce at most one change per 30 minutes, without inventing new orders."""
    repaired = list(orders)
    last_change = -MIN_INTERVAL_STEPS
    for index in range(1, len(repaired)):
        if repaired[index] is not repaired[index - 1]:
            if index - last_change < MIN_INTERVAL_STEPS:
                repaired[index] = repaired[index - 1]
            else:
                last_change = index
    return repaired


@dataclass(slots=True)
class _Context:
    """Everything the evaluation needs, kept in one object for clarity."""

    params: ModelParameters
    ladder: Ladder
    t_min: list[float]
    prices: list[float]
    t_ext: list[float]
    p_max: float
    band: float
    lam: float
    t_prev2: float
    t_prev1: float

    @property
    def steps(self) -> int:
        return len(self.prices)


def _evaluate(ctx: _Context, orders: list[Order]) -> tuple[float, float, list[float]]:
    """Simulate one full horizon. Returns ``(cost, penalty, temperatures)``."""
    params = ctx.params
    t2, t1 = ctx.t_prev2, ctx.t_prev1
    cost = 0.0
    penalty = 0.0
    temps: list[float] = []

    for index, order in enumerate(orders):
        power = power_for(order, t1, ctx.ladder, ctx.p_max, ctx.band)
        t_next = (
            params.a1 * t1
            + params.a2 * t2
            + params.be * ctx.t_ext[index]
            + params.bp * power
            + params.c
        )
        cost += ctx.prices[index] * power * DT_HOURS / 1000.0
        deficit = max(0.0, ctx.t_min[index] - t_next)
        penalty += ctx.lam * DT_HOURS * deficit * deficit
        if t_next < HARD_FLOOR:
            penalty += INFEASIBLE_PENALTY * (HARD_FLOOR - t_next) * DT_HOURS
        temps.append(t_next)
        t2, t1 = t1, t_next

    return cost, penalty, temps


def _greedy(ctx: _Context) -> list[Order]:
    """Pick, step by step, the order with the cheapest 2 h lookahead."""
    orders: list[Order] = []
    t2, t1 = ctx.t_prev2, ctx.t_prev1
    last_change = -MIN_INTERVAL_STEPS

    for index in range(ctx.steps):
        candidates: list[Order]
        if orders and index - last_change < MIN_INTERVAL_STEPS:
            candidates = [orders[-1]]
        else:
            candidates = list(ACTIVE_ORDERS)

        best_order = candidates[0]
        best_score = float("inf")
        for order in candidates:
            local = _lookahead(ctx, order, index, t2, t1)
            if local < best_score:
                best_score, best_order = local, order

        if orders and best_order is not orders[-1]:
            last_change = index
        orders.append(best_order)

        power = power_for(best_order, t1, ctx.ladder, ctx.p_max, ctx.band)
        t_next = (
            ctx.params.a1 * t1
            + ctx.params.a2 * t2
            + ctx.params.be * ctx.t_ext[index]
            + ctx.params.bp * power
            + ctx.params.c
        )
        t2, t1 = t1, t_next

    return orders


def _lookahead(
    ctx: _Context, first: Order, start: int, t2: float, t1: float, *, horizon: int = LOOKAHEAD
) -> float:
    """Cost of holding ``first`` for ``horizon`` steps, starting at ``start``."""
    score = 0.0
    for offset in range(horizon):
        index = start + offset
        if index >= ctx.steps:
            break
        power = power_for(first, t1, ctx.ladder, ctx.p_max, ctx.band)
        t_next = (
            ctx.params.a1 * t1
            + ctx.params.a2 * t2
            + ctx.params.be * ctx.t_ext[index]
            + ctx.params.bp * power
            + ctx.params.c
        )
        deficit = max(0.0, ctx.t_min[index] - t_next)
        score += ctx.prices[index] * power * DT_HOURS / 1000.0
        score += ctx.lam * DT_HOURS * deficit * deficit
        t2, t1 = t1, t_next
    return score


def _improve(
    ctx: _Context, orders: list[Order], cost: float, penalty: float, budget: int
) -> tuple[list[Order], float, float, int]:
    """Random block flips, accepted only when the objective improves."""
    rng = random.Random(SEED)
    best = list(orders)
    best_cost, best_penalty = cost, penalty
    evaluations = 0

    while evaluations < budget:
        evaluations += 1
        candidate = list(best)
        start = rng.randrange(ctx.steps)
        length = rng.choice((4, 6, 8))
        order = rng.choice(ACTIVE_ORDERS)
        for index in range(start, min(start + length, ctx.steps)):
            candidate[index] = order
        candidate = _repair(candidate)

        new_cost, new_penalty, _temps = _evaluate(ctx, candidate)
        if new_cost + new_penalty < best_cost + best_penalty - 1e-9:
            best, best_cost, best_penalty = candidate, new_cost, new_penalty

    return best, best_cost, best_penalty, evaluations


def evaluate_orders(
    *,
    params: ModelParameters,
    ladder: Ladder,
    t_min: list[float],
    prices: list[float],
    t_ext: list[float],
    t_now: float,
    t_prev: float,
    p_max: float,
    orders: list[Order],
    band: float = DEFAULT_BAND,
    lam: float = DEFAULT_LAMBDA,
) -> tuple[float, float, list[float]]:
    """Public wrapper around the internal simulation, used for comparisons."""
    ctx = _Context(
        params=params,
        ladder=ladder,
        t_min=t_min,
        prices=prices,
        t_ext=t_ext,
        p_max=max(1.0, p_max),
        band=band,
        lam=lam,
        t_prev2=t_prev,
        t_prev1=t_now,
    )
    return _evaluate(ctx, orders)


def build_plan(
    *,
    params: ModelParameters,
    ladder: Ladder,
    t_min: list[float],
    prices: list[float],
    t_ext: list[float],
    t_now: float,
    t_prev: float,
    p_max: float,
    start: datetime,
    band: float = DEFAULT_BAND,
    lam: float = DEFAULT_LAMBDA,
    budget: int = BUDGET,
) -> Plan:
    """Build the cheapest feasible 24 h plan."""
    ctx = _Context(
        params=params,
        ladder=ladder,
        t_min=t_min,
        prices=prices,
        t_ext=t_ext,
        p_max=max(1.0, p_max),
        band=band,
        lam=lam,
        t_prev2=t_prev,
        t_prev1=t_now,
    )

    orders = _greedy(ctx)
    cost, penalty, _temps = _evaluate(ctx, orders)
    orders, cost, penalty, evaluations = _improve(ctx, orders, cost, penalty, budget)

    _cost, _penalty, temps = _evaluate(ctx, orders)
    steps: list[Step] = []
    for index, order in enumerate(orders):
        moment = start + timedelta(minutes=15 * index)
        power = power_for(order, temps[index - 1] if index else t_now, ladder, ctx.p_max, band)
        steps.append(
            Step(
                moment=moment,
                order=order,
                t_pred=round(temps[index], 2),
                price=prices[index],
                power=round(power, 0),
                cost=round(prices[index] * power * DT_HOURS / 1000.0, 5),
            )
        )

    changes = sum(1 for index in range(1, len(orders)) if orders[index] is not orders[index - 1])
    return Plan(
        steps=tuple(steps),
        cost=round(cost, 4),
        penalty=round(penalty, 4),
        changes=changes,
        min_temp=round(min(temps), 2) if temps else t_now,
        feasible=bool(temps) and min(temps) >= HARD_FLOOR,
        evaluations=evaluations,
    )
