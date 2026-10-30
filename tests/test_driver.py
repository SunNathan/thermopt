"""Fil pilote driver tests (pure logic only, no Home Assistant runtime)."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.limiters import WriteLimiter
from core.orders import Order, order_from_z2m, z2m_value

NOW = datetime(2026, 1, 5, 12, 0)


def test_z2m_mapping_is_lossless_for_the_five_orders() -> None:
    for order in Order:
        assert order_from_z2m(z2m_value(order)) is order


def test_order_from_z2m_rejects_off() -> None:
    assert order_from_z2m("off") is None
    assert order_from_z2m("OFF") is None


def test_order_from_z2m_tolerates_case_and_spaces() -> None:
    assert order_from_z2m(" Comfort_-2 ") is Order.COMFORT_2


def test_limiter_rejects_unchanged_order() -> None:
    limiter = WriteLimiter()
    decision = limiter.check(NOW, Order.COMFORT, Order.COMFORT)
    assert decision.allowed is False
    assert decision.reason == "unchanged"


def test_limiter_enforces_dwell_time() -> None:
    limiter = WriteLimiter()
    limiter.record(NOW)
    decision = limiter.check(NOW + timedelta(minutes=2), Order.ECO, Order.COMFORT)
    assert decision.allowed is False
    assert decision.reason == "dwell_time"


def test_limiter_allows_after_dwell_and_window() -> None:
    limiter = WriteLimiter()
    limiter.record(NOW)
    assert limiter.check(NOW + timedelta(minutes=31), Order.ECO, Order.COMFORT).allowed


def test_limiter_enforces_max_changes_per_window() -> None:
    limiter = WriteLimiter()
    limiter.record(NOW)
    decision = limiter.check(NOW + timedelta(minutes=10), Order.ECO, Order.COMFORT)
    assert decision.allowed is False
    assert decision.reason == "rate_limit"
