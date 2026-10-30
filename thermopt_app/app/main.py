"""Entry point of the ThermOpt app.

Milestone B: configuration, perception and safety. The container talks to Home
Assistant through the Supervisor proxy, publishes its entities with MQTT
discovery, and executes the guard rails when the app is in active mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import signal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import AppConfig
from .ha import HaClient
from .history import HistoryStore
from .loop import SupervisionLoop
from .model import ModelParameters
from .mqtt import MqttPublisher
from .options import Options
from .publish import Publisher
from .store import JsonStore
from .supervisor import SupervisorClient, SupervisorError
from .web import WebRuntime, start_site

_LOGGER = logging.getLogger(__name__)

VERSION = os.environ.get("THERMOPT_VERSION", "dev")
MODEL_PATH = "/data/model.json"
STARTUP_RETRIES = 10
STARTUP_DELAY = 6
HEALTH_INTERVAL = 30
MAINTENANCE_INTERVAL = 24 * 3600


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _connect(runtime: WebRuntime) -> SupervisorClient:
    client = SupervisorClient()
    await client.__aenter__()

    for attempt in range(1, STARTUP_RETRIES + 1):
        try:
            config = await client.core_config()
        except SupervisorError as err:
            _LOGGER.warning(
                "Home Assistant pas encore prêt (%s/%s) : %s", attempt, STARTUP_RETRIES, err
            )
            await asyncio.sleep(STARTUP_DELAY)
            continue

        runtime.ha_version = str(config.get("version", "?"))
        runtime.ha_location = str(config.get("location_name") or "")
        _LOGGER.info("Connecté à Home Assistant %s", runtime.ha_version)
        return client

    raise SupervisorError("Home Assistant injoignable après plusieurs tentatives")


def _load_models(store: JsonStore) -> dict[str, ModelParameters]:
    """Read the identified models; a corrupt file must not block startup."""
    payload = store.load() or {}
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    if not isinstance(rooms, dict):
        return {}
    models: dict[str, ModelParameters] = {}
    for room_id, data in rooms.items():
        params = ModelParameters.from_dict(data if isinstance(data, dict) else None)
        if params is not None:
            models[str(room_id)] = params
    return models


def _timezone(name: str | None):
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            _LOGGER.warning("Fuseau inconnu %s, UTC utilisé", name)
    return ZoneInfo("UTC")


async def _maintenance_loop(history, stop: asyncio.Event) -> None:
    """Prune old months and watch the disk, once a day."""
    while not stop.is_set():
        await asyncio.to_thread(history.prune)
        await asyncio.to_thread(history.refresh_disk)
        try:
            await asyncio.wait_for(stop.wait(), timeout=MAINTENANCE_INTERVAL)
        except TimeoutError:
            continue


async def _health_loop(runtime: WebRuntime, stop: asyncio.Event) -> None:
    """Keep the web page honest even when MQTT drops."""
    while not stop.is_set():
        runtime.healthy = runtime.mqtt_connected and runtime.loop is not None
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEALTH_INTERVAL)
        except TimeoutError:
            continue


async def run() -> None:
    options = Options.load()
    _configure_logging(options.log_level)
    _LOGGER.info("ThermOpt app %s démarrage (%s)", VERSION, platform.machine())

    store = JsonStore()
    config = AppConfig.from_dict(store.load())
    runtime = WebRuntime(VERSION, config)

    history = HistoryStore()
    model_store = JsonStore(Path(MODEL_PATH))
    models = _load_models(model_store)
    runtime.history = history
    runtime.models = models

    runner = await start_site(runtime)

    client: SupervisorClient | None = None
    mqtt: MqttPublisher | None = None
    loop_task: asyncio.Task | None = None
    health_task: asyncio.Task | None = None
    maintenance_task: asyncio.Task | None = None
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        _LOGGER.info("Arrêt demandé")
        stop.set()

    asyncio_loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - Windows
            asyncio_loop.add_signal_handler(sig, _stop)

    try:
        client = await _connect(runtime)
        core_config = await client.core_config()
        tz = _timezone(core_config.get("time_zone"))

        ha = HaClient(client)
        await ha.refresh_states()
        runtime.states = ha.cached()

        try:
            credentials = await client.mqtt_service()
        except SupervisorError as err:
            runtime.mqtt_detail = f"broker indisponible : {err}"
            _LOGGER.error("Broker MQTT indisponible : %s", err)
            publisher = None
        else:
            mqtt = MqttPublisher(credentials)
            await mqtt.start()
            await asyncio.sleep(2)
            runtime.mqtt_connected = mqtt.connected
            runtime.mqtt_detail = f"{credentials.host}:{credentials.port}"
            publisher = Publisher(mqtt, VERSION)

        if publisher is None:
            raise SupervisorError("MQTT requis pour publier les entités")

        supervisor_loop = SupervisionLoop(ha, publisher, config, tz, history, models)
        runtime.loop = supervisor_loop

        await publisher.publish_discovery(config)

        def save_config(candidate: AppConfig) -> None:
            store.backup()
            store.save(candidate.to_dict())
            runtime.config = candidate
            asyncio.create_task(publisher.publish_discovery(candidate))

        def save_models(current: dict[str, ModelParameters]) -> None:
            model_store.save(
                {"rooms": {room_id: params.to_dict() for room_id, params in current.items()}}
            )

        runtime.save_config = save_config
        runtime.save_models = save_models

        loop_task = asyncio.create_task(supervisor_loop.run(stop), name="supervision")
        health_task = asyncio.create_task(_health_loop(runtime, stop), name="health")
        maintenance_task = asyncio.create_task(_maintenance_loop(history, stop), name="maintenance")

        await stop.wait()

    finally:
        stop.set()
        for task in (loop_task, health_task, maintenance_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if mqtt is not None:
            await mqtt.stop()
        if client is not None:
            await client.close()
        await runner.cleanup()
        _LOGGER.info("ThermOpt app arrêtée")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
