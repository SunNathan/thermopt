"""Order ladder tests."""

from __future__ import annotations

import pytest

from core.orders import (
    ACTIVE_ORDERS,
    Ladder,
    Order,
    is_colder,
    order_from_z2m,
    z2m_value,
)


def test_ladder_with_recommended_setpoint() -> None:
    ladder = Ladder(comfort=20.5, frost=7.0)
    assert ladder.setpoint(Order.COMFORT) == 20.5
    assert ladder.setpoint(Order.COMFORT_1) == 19.5
    assert ladder.setpoint(Order.COMFORT_2) == 18.5
    assert ladder.setpoint(Order.ECO) == 17.0
    assert ladder.setpoint(Order.FROST) == 7.0


def test_ladder_order_is_warmest_first() -> None:
    ladder = Ladder(comfort=20.5)
    assert list(ladder.setpoints()) == [
        Order.COMFORT,
        Order.COMFORT_1,
        Order.COMFORT_2,
        Order.ECO,
        Order.FROST,
    ]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (19.5, Order.COMFORT_1),
        (17.0, Order.ECO),
        (18.6, Order.COMFORT_2),
        (20.4, Order.COMFORT),
        (16.0, Order.ECO),
    ],
)
def test_nearest(target: float, expected: Order) -> None:
    assert Ladder().nearest(target) is expected


def test_nearest_never_returns_frost_by_default() -> None:
    assert Ladder().nearest(7.0) is Order.ECO


def test_frost_only_when_explicitly_allowed() -> None:
    assert Ladder().nearest(7.0, include_frost=True) is Order.FROST


def test_reachable() -> None:
    ladder = Ladder(comfort=20.5)
    assert ladder.reachable(17.0)
    assert ladder.reachable(19.5)
    assert ladder.reachable(17.3, tolerance=0.5)
    assert not ladder.reachable(17.4, tolerance=0.2)


def test_default_setpoint_forces_dithering() -> None:
    """C = 20 leaves 17 °C and 19.5 °C half a degree away (§ spec 2.2)."""
    ladder = Ladder(comfort=20.0)
    assert ladder.nearest(17.0) is Order.ECO  # 16.5
    assert ladder.nearest(19.5) is Order.COMFORT  # 20.0
    assert ladder.reachable(17.0, 0.2) is False
    assert ladder.reachable(17.0, 0.5) is True


def test_closest_below() -> None:
    ladder = Ladder(comfort=20.5)
    assert ladder.closest_below(19.5) is Order.COMFORT_1
    assert ladder.closest_below(17.2) is Order.ECO


def test_rank_comparison() -> None:
    assert is_colder(Order.ECO, Order.COMFORT)
    assert not is_colder(Order.COMFORT, Order.ECO)


def test_off_is_never_an_order() -> None:
    assert "off" not in {o.value for o in Order}
    assert order_from_z2m("off") is None
    assert order_from_z2m(None) is None


def test_z2m_mapping() -> None:
    assert z2m_value(Order.COMFORT_1) == "comfort_-1"
    assert z2m_value(Order.FROST) == "frost_protection"
    for order in Order:
        assert order_from_z2m(z2m_value(order)) is order


def test_active_orders_exclude_frost() -> None:
    assert Order.FROST not in ACTIVE_ORDERS
    assert len(ACTIVE_ORDERS) == 4
