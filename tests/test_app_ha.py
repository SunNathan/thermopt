"""Tests for the Home Assistant response parsing."""

from __future__ import annotations

from app.ha import extract_forecast

ENTITY = "weather.home"

FORECAST = [
    {"datetime": "2026-01-01T00:00:00+00:00", "temperature": 4.5},
    {"datetime": "2026-01-01T01:00:00+00:00", "temperature": 4.0},
    {"datetime": "2026-01-01T02:00:00+00:00", "temperature": None},
]


def test_reads_the_wrapped_service_response() -> None:
    """This is the real shape of a REST call with ?return_response."""
    payload = {"changed_states": [], "service_response": {ENTITY: {"forecast": FORECAST}}}
    points = extract_forecast(payload, ENTITY)

    assert len(points) == 2
    assert points[0][1] == 4.5


def test_reads_the_unwrapped_form() -> None:
    payload = {ENTITY: {"forecast": FORECAST}}
    assert len(extract_forecast(payload, ENTITY)) == 2


def test_ignores_unknown_entity() -> None:
    payload = {"service_response": {"weather.other": {"forecast": FORECAST}}}
    assert extract_forecast(payload, ENTITY) == []


def test_ignores_garbage() -> None:
    assert extract_forecast(None, ENTITY) == []
    assert extract_forecast("nope", ENTITY) == []
    assert extract_forecast({"service_response": []}, ENTITY) == []
    assert extract_forecast({"service_response": {ENTITY: {"forecast": "x"}}}, ENTITY) == []


def test_skips_items_without_temperature() -> None:
    payload = {
        "service_response": {ENTITY: {"forecast": [{"datetime": "2026-01-01T00:00:00+00:00"}]}}
    }
    assert extract_forecast(payload, ENTITY) == []


def test_skips_invalid_dates() -> None:
    payload = {
        "service_response": {ENTITY: {"forecast": [{"datetime": "pas une date", "temperature": 3}]}}
    }
    assert extract_forecast(payload, ENTITY) == []
