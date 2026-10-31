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


# ---------------------------------------------------------------------------
# Targeted refresh (dashboard polling)
# ---------------------------------------------------------------------------
class _Api:
    """Stand-in for SupervisorClient.get."""

    def __init__(self, payloads: dict) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    async def get(self, path: str) -> object:
        self.calls.append(path)
        value = self.payloads[path]
        if isinstance(value, Exception):
            raise value
        return value


async def test_refresh_entities_merges_the_requested_ones() -> None:
    from app.ha import EntityState, HaClient
    from app.supervisor import SupervisorError

    api = _Api(
        {
            "/core/api/states/sensor.t": {
                "entity_id": "sensor.t",
                "state": "20.4",
                "attributes": {"unit_of_measurement": "°C"},
            },
            "/core/api/states/sensor.gone": SupervisorError("404"),
        }
    )
    ha = HaClient(api)  # type: ignore[arg-type]
    ha._states = {"sensor.other": EntityState("sensor.other", "1", {})}

    await ha.refresh_entities(["sensor.t", "sensor.gone", "sensor.t"])

    assert ha.cached()["sensor.t"].state == "20.4"
    assert ha.cached()["sensor.other"].state == "1"  # untouched
    assert len([call for call in api.calls if call.endswith("sensor.t")]) == 1


async def test_refresh_entities_ignores_garbage() -> None:
    from app.ha import HaClient

    api = _Api({"/core/api/states/sensor.t": "nope"})
    ha = HaClient(api)  # type: ignore[arg-type]

    await ha.refresh_entities(["sensor.t"])
    assert ha.cached() == {}
