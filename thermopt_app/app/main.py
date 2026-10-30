"""Entry point of the ThermOpt app.

Milestone A: prove the delivery chain. The container connects to the Supervisor,
publishes one MQTT-discovered entity, serves an ingress page and a health
endpoint. The supervision loop, the safety layer and the configuration UI are
added in the next milestones.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import signal
from datetime import datetime

from .discovery import (
    AVAILABILITY_TOPIC,
    HEALTH_ATTRIBUTES_TOPIC,
    HEALTH_STATE_TOPIC,
    PAYLOAD_ONLINE,
    build_health_config,
    health_config_topic,
)
from .mqtt import MqttPublisher
from .options import Options
from .supervisor import SupervisorClient, SupervisorError
from .web import WebRuntime, start_site

_LOGGER = logging.getLogger(__name__)

VERSION = os.environ.get("THERMOPT_VERSION", "dev")
PUBLISH_INTERVAL = 30
STARTUP_RETRIES = 10
STARTUP_DELAY = 6


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _connect_supervisor(runtime: WebRuntime) -> SupervisorClient:
    """Retry until Home Assistant is reachable, then record what we learned."""
    client = SupervisorClient()
    await client.__aenter__()

    for attempt in range(1, STARTUP_RETRIES + 1):
        try:
            config = await client.core_config()
        except SupervisorError as err:
            _LOGGER.warning("Home Assistant not ready (%s/%s): %s", attempt, STARTUP_RETRIES, err)
            await asyncio.sleep(STARTUP_DELAY)
            continue

        runtime.ha_version = str(config.get("version", "?"))
        runtime.ha_location = str(config.get("location_name") or config.get("time_zone") or "")
        _LOGGER.info("Connected to Home Assistant %s", runtime.ha_version)
        return client

    raise SupervisorError("Home Assistant unreachable after retries")


async def _publish_state(publisher: MqttPublisher, runtime: WebRuntime) -> None:
    healthy = runtime.mqtt_connected
    await publisher.publish(HEALTH_STATE_TOPIC, "ok" if healthy else "degraded")
    await publisher.publish_json(
        HEALTH_ATTRIBUTES_TOPIC,
        {
            "version": runtime.version,
            "home_assistant": runtime.ha_version,
            "mqtt": runtime.mqtt_connected,
            "architecture": platform.machine(),
            "started_at": runtime.started_at.isoformat(timespec="seconds"),
            "heartbeat": datetime.now().isoformat(timespec="seconds"),
        },
    )


async def run() -> None:
    options = Options.load()
    _configure_logging(options.log_level)
    _LOGGER.info("ThermOpt app %s starting (%s)", VERSION, platform.machine())

    runtime = WebRuntime(VERSION)
    runner = await start_site(runtime)

    client: SupervisorClient | None = None
    publisher: MqttPublisher | None = None
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        _LOGGER.info("Stopping")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - Windows
            loop.add_signal_handler(sig, _stop)

    try:
        client = await _connect_supervisor(runtime)

        try:
            credentials = await client.mqtt_service()
        except SupervisorError as err:
            runtime.mqtt_detail = f"broker indisponible : {err}"
            _LOGGER.error("MQTT broker unavailable: %s", err)
        else:
            publisher = MqttPublisher(credentials)
            await publisher.start()
            await asyncio.sleep(2)  # let the connection come up

            runtime.mqtt_connected = publisher.connected
            runtime.mqtt_detail = f"{credentials.host}:{credentials.port}"
            runtime.healthy = True

            await publisher.publish_json(health_config_topic(), build_health_config(VERSION))
            await publisher.publish(AVAILABILITY_TOPIC, PAYLOAD_ONLINE, retain=True)
            await _publish_state(publisher, runtime)

        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=PUBLISH_INTERVAL)

            if publisher is not None:
                runtime.mqtt_connected = publisher.connected
                runtime.healthy = publisher.connected
                await _publish_state(publisher, runtime)

    finally:
        if publisher is not None:
            await publisher.stop()
        if client is not None:
            await client.close()
        await runner.cleanup()
        _LOGGER.info("ThermOpt app stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
