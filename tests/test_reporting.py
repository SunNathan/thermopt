"""Pure tests for the degradation messages."""

from __future__ import annotations

from custom_components.thermopt.core.orders import Ladder, Order
from custom_components.thermopt.perception.comfort import ComfortProfile
from custom_components.thermopt.reporting import (
    describe_profile_issue,
    describe_reason,
    fmt,
)


def test_fmt_uses_french_comma() -> None:
    assert fmt(20.5) == "20,5"
    assert fmt(16.55, 2) == "16,55"


def test_eco_below_floor_explains_the_arithmetic() -> None:
    ladder = Ladder(comfort=20.0)
    message = describe_profile_issue("eco_below_floor:17.0", ladder)

    assert "16,5" in message  # Eco with C = 20
    assert "17,0" in message  # the comfort floor
    assert "20,5" in message  # the setpoint to use instead
    assert "Confort" in message


def test_unreachable_target_is_named() -> None:
    ladder = Ladder(comfort=20.5)
    message = describe_profile_issue("unreachable:22.0", ladder)
    assert "22,0" in message
    assert "20,5" in message


def test_unknown_issue_is_passed_through() -> None:
    assert describe_profile_issue("weird", Ladder()) == "weird"


def test_reason_includes_the_room() -> None:
    message = describe_reason("sensor_frozen", room="Salon")
    assert message.startswith("Pièce « Salon »")


def test_relay_message_is_actionable() -> None:
    message = describe_reason("relay_off", room="Chambre")
    assert "relai" in message.lower()
    assert "remis en marche" in message


def test_profile_reason_uses_the_issue_when_available() -> None:
    ladder = Ladder(comfort=20.0)
    message = describe_reason("profile_unreachable", ladder=ladder, issue="eco_below_floor:17.0")
    assert "20,5" in message


def test_default_ladder_is_consistent() -> None:
    """The recommended setpoint must not produce any degradation."""
    from perception.comfort import profile_issues

    ladder = Ladder(comfort=20.5)
    assert profile_issues(ComfortProfile(), ladder, ladder.setpoint(Order.ECO)) == []


def test_default_profile_with_20_degrees_is_flagged() -> None:
    from perception.comfort import profile_issues

    ladder = Ladder(comfort=20.0)
    issues = profile_issues(ComfortProfile(), ladder, ladder.setpoint(Order.ECO))
    assert issues == ["eco_below_floor:17.0"]


def test_message_mentions_eco_when_it_is_explicit() -> None:
    """With an absolute Eco, changing Comfort would not move Eco: say so."""
    ladder = Ladder(comfort=20.5, eco=16.5)
    message = describe_profile_issue("eco_below_floor:17.0", ladder)

    assert "Eco" in message
    assert "17,0" in message
    assert "Confort du radiateur" not in message
