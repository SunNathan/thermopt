"""Web layer tests: relative redirects and form handling.

Under ingress the app is served at ``/api/hassio_ingress/<token>/``; an absolute
redirect to ``/`` would send the browser to Home Assistant's home page instead
of the app's.
"""

from __future__ import annotations

from dataclasses import replace

from aiohttp.test_utils import TestClient, TestServer

from app.config import AppConfig, RoomConfig
from app.web import REDIRECT_HOME, WebRuntime, create_app

FORM = {
    "room_0_id": "abc",
    "room_0_name": "Salon",
    "room_0_temp": "sensor.salon_temperature",
    "room_0_fil": "select.salon_pilot_wire_mode",
    "weather_entity": "weather.home",
    "fallback_entity": "input_boolean.thermopt_repli",
    "hp_price": "0.2065",
    "hc_price": "0.1579",
    "hc_windows": "22:00-06:00, 12:00-14:00",
    "comfort_setpoint": "20.5",
    "frost_setpoint": "7",
    "start_night": "23:00",
    "start_morning": "06:30",
    "start_day": "08:30",
    "start_evening": "17:30",
    "weekday_night": "17",
    "weekday_morning": "19.5",
    "weekday_day": "17",
    "weekday_evening": "19.5",
    "weekend_night": "17",
    "weekend_morning": "19.5",
    "weekend_day": "19",
    "weekend_evening": "19.5",
    "present_day": "19",
    "tolerance": "0.3",
    "high_margin": "1",
    "active": "on",
}


def _runtime() -> WebRuntime:
    config = AppConfig(
        rooms=(
            RoomConfig(
                id="abc",
                name="Salon",
                temp_entity="sensor.salon_temperature",
                fil_pilote_entity="select.salon_pilot_wire_mode",
            ),
        )
    )
    runtime = WebRuntime("0.4.1", config)
    runtime.healthy = True
    runtime.mqtt_connected = True
    return runtime


async def _client(runtime: WebRuntime) -> TestClient:
    client = TestClient(TestServer(create_app(runtime)))
    await client.start_server()
    return client


async def test_config_save_redirects_relatively() -> None:
    client = await _client(_runtime())
    try:
        response = await client.post("/config", data=FORM, allow_redirects=False)
        location = response.headers.get("Location", "")

        assert response.status == 302
        assert location == "./", location
        assert not location.startswith("/")
    finally:
        await client.close()


async def test_toggle_active_redirects_relatively() -> None:
    client = await _client(_runtime())
    try:
        response = await client.post("/active", allow_redirects=False)
        location = response.headers.get("Location", "")

        assert response.status == 302
        assert not location.startswith("/")
    finally:
        await client.close()


async def test_invalid_config_is_refused_without_redirect() -> None:
    client = await _client(_runtime())
    try:
        broken = dict(FORM)
        broken["hc_windows"] = "n'importe quoi"
        response = await client.post("/config", data=broken, allow_redirects=False)

        assert response.status == 200
        assert "Heures Creuses" in await response.text()
    finally:
        await client.close()


async def test_saving_persists_through_the_callback() -> None:
    runtime = _runtime()
    saved: list[AppConfig] = []
    runtime.save_config = saved.append

    client = await _client(runtime)
    try:
        await client.post("/config", data=FORM, allow_redirects=False)
        assert len(saved) == 1
        assert saved[0].rooms[0].name == "Salon"
        assert saved[0].comfort_setpoint == 20.5
    finally:
        await client.close()


async def test_home_page_renders() -> None:
    client = await _client(_runtime())
    try:
        response = await client.get("/")
        body = await response.text()
        assert response.status == 200
        assert "ThermOpt" in body
        assert 'href="./"' in body
    finally:
        await client.close()


def test_redirect_target_is_relative() -> None:
    """Cheap guard: the constant itself must never become absolute."""
    assert REDIRECT_HOME == "./"
    assert not REDIRECT_HOME.startswith("/")


# ---------------------------------------------------------------------------
# Supervisor detection
# ---------------------------------------------------------------------------
def _app_owned_states() -> dict:
    from app.ha import EntityState

    return {
        "sensor.thermopt_statut": EntityState("sensor.thermopt_statut", "actif", {}),
        "sensor.thermopt_prix_actuel": EntityState("sensor.thermopt_prix_actuel", "0.2", {}),
        "sensor.thermopt_dernier_cycle": EntityState(
            "sensor.thermopt_dernier_cycle", "2026-01-01", {}
        ),
        "sensor.thermopt_salon_temperature": EntityState(
            "sensor.thermopt_salon_temperature", "21", {}
        ),
    }


def test_own_entities_do_not_trigger_the_warning() -> None:
    """The app used to detect itself: it publishes sensor.thermopt_* too."""
    runtime = _runtime()
    runtime.states = _app_owned_states()
    assert runtime.supervisor_markers == []
    assert runtime.integration_present is False


def test_legacy_signature_is_detected() -> None:
    from app.ha import EntityState

    runtime = _runtime()
    runtime.states = {
        **_app_owned_states(),
        "sensor.thermopt_prochain_cycle": EntityState(
            "sensor.thermopt_prochain_cycle", "2026-01-01", {}
        ),
    }
    assert runtime.integration_present is True


def test_unavailable_orphan_is_ignored() -> None:
    from app.ha import EntityState

    runtime = _runtime()
    runtime.states = {
        **_app_owned_states(),
        "sensor.thermopt_prochain_cycle": EntityState(
            "sensor.thermopt_prochain_cycle", "unavailable", {}
        ),
    }
    assert runtime.supervisor_markers == []
    assert runtime.integration_present is False


def test_acknowledgement_hides_the_warning() -> None:
    from app.ha import EntityState

    runtime = _runtime()
    runtime.states = {
        **_app_owned_states(),
        "sensor.thermopt_pieces": EntityState("sensor.thermopt_pieces", "1", {}),
    }
    assert runtime.integration_present is True

    runtime.config = replace(runtime.config, supervisor_ack=True)
    assert runtime.integration_present is False


# ---------------------------------------------------------------------------
# Weather card
# ---------------------------------------------------------------------------
def test_weather_card_reads_the_current_temperature() -> None:
    from app.ha import EntityState

    runtime = _runtime()
    runtime.config = replace(runtime.config, weather_entity="weather.home")
    runtime.states = {
        "weather.home": EntityState(
            "weather.home", "cloudy", {"temperature": 6.4, "friendly_name": "Météo"}
        )
    }

    card = runtime.weather()
    assert card["entity"] == "weather.home"
    assert card["state"] == "cloudy"
    assert card["temperature"] == 6.4


def test_weather_card_handles_a_missing_attribute() -> None:
    from app.ha import EntityState

    runtime = _runtime()
    runtime.config = replace(runtime.config, weather_entity="weather.home")
    runtime.states = {"weather.home": EntityState("weather.home", "sunny", {})}

    assert runtime.weather()["temperature"] is None


async def test_optimizer_flag_is_persisted() -> None:
    runtime = _runtime()
    saved: list = []
    runtime.save_config = saved.append

    client = await _client(runtime)
    try:
        payload = dict(FORM)
        payload["optimizer_active"] = "on"
        await client.post("/config", data=payload, allow_redirects=False)

        assert saved and saved[0].optimizer_active is True
    finally:
        await client.close()


async def test_optimizer_is_off_by_default() -> None:
    runtime = _runtime()
    saved: list = []
    runtime.save_config = saved.append

    client = await _client(runtime)
    try:
        await client.post("/config", data=FORM, allow_redirects=False)
        assert saved and saved[0].optimizer_active is False
    finally:
        await client.close()


async def test_eco_setpoint_is_persisted() -> None:
    runtime = _runtime()
    saved: list = []
    runtime.save_config = saved.append

    client = await _client(runtime)
    try:
        payload = dict(FORM)
        payload["eco_setpoint"] = "17.5"
        await client.post("/config", data=payload, allow_redirects=False)

        assert saved and saved[0].eco_setpoint == 17.5
    finally:
        await client.close()


async def test_empty_eco_means_derived() -> None:
    runtime = _runtime()
    saved: list = []
    runtime.save_config = saved.append

    client = await _client(runtime)
    try:
        payload = dict(FORM)
        payload["eco_setpoint"] = ""
        await client.post("/config", data=payload, allow_redirects=False)

        assert saved and saved[0].eco_setpoint is None
    finally:
        await client.close()


def test_eco_must_sit_between_frost_and_comfort() -> None:
    from app.config import validate

    config = AppConfig(
        rooms=(
            RoomConfig(id="a", name="Salon", temp_entity="sensor.t", fil_pilote_entity="select.f"),
        ),
    )
    assert validate(config) == []

    too_high = replace(config, eco_setpoint=20.5)
    assert any("Eco" in error for error in validate(too_high))

    too_low = replace(config, eco_setpoint=6.0)
    assert any("Eco" in error for error in validate(too_low))


# ---------------------------------------------------------------------------
# Mode toggle
# ---------------------------------------------------------------------------
class _LoopStub:
    """The web layer only needs the mode and a way to reload the config."""

    def __init__(self) -> None:
        self.mode = "actif"
        self.last_cycle = None
        self.last_snapshot = None
        self.degraded: list[str] = []
        self.forecast_count = 0
        self.forecast_error = None
        self.cycles = 0
        self.config = None
        self.rooms: dict = {}

    def apply_config(self, config) -> None:
        self.config = config
        self.mode = "actif" if config.active else "observation"

    async def cycle(self) -> None:
        self.cycles += 1


async def test_toggle_switches_to_observation_immediately() -> None:
    runtime = _runtime()
    stub = _LoopStub()
    runtime.loop = stub  # type: ignore[assignment]

    client = await _client(runtime)
    try:
        response = await client.post("/active", allow_redirects=False)
        assert response.status == 302

        assert stub.mode == "observation"
        assert stub.cycles == 1

        page = await client.get("/")
        body = await page.text()
        assert "observation" in body
    finally:
        await client.close()


async def test_home_page_no_longer_shows_the_ha_version() -> None:
    runtime = _runtime()
    runtime.ha_version = "2026.10.7"
    runtime.loop = _LoopStub()  # type: ignore[assignment]

    client = await _client(runtime)
    try:
        body = await (await client.get("/")).text()
        assert "2026.10.7" not in body
        assert "Home Assistant" not in body
    finally:
        await client.close()
