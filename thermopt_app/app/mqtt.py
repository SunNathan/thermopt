"""MQTT connection and discovery publishing.

The broker is the one already installed for Zigbee2MQTT; the Supervisor hands
over the credentials, so the user never types them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from aiomqtt import Client, MqttError, Will

from .discovery import (
    AVAILABILITY_TOPIC,
    PAYLOAD_OFFLINE,
    PAYLOAD_ONLINE,
    health_config_topic,
)
from .supervisor import MqttCredentials

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 5
CLIENT_ID = "thermopt-app"


class MqttPublisher:
    """Keeps a connection open, reconnecting forever."""

    def __init__(self, credentials: MqttCredentials) -> None:
        self._credentials = credentials
        self._client: Client | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self.connected = False
        self.last_error: str | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="mqtt")

    async def stop(self) -> None:
        self._stopping.set()
        await self.publish(AVAILABILITY_TOPIC, PAYLOAD_OFFLINE, retain=True)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, MqttError):
                await self._task
            self._task = None
        self.connected = False

    async def _run(self) -> None:
        credentials = self._credentials
        while not self._stopping.is_set():
            try:
                async with Client(
                    hostname=credentials.host,
                    port=credentials.port,
                    username=credentials.username,
                    password=credentials.password,
                    identifier=CLIENT_ID,
                    will=Will(
                        topic=AVAILABILITY_TOPIC,
                        payload=PAYLOAD_OFFLINE,
                        retain=True,
                    ),
                ) as client:
                    self._client = client
                    self.connected = True
                    self.last_error = None
                    _LOGGER.info("MQTT connected to %s:%s", credentials.host, credentials.port)
                    await self.publish(AVAILABILITY_TOPIC, PAYLOAD_ONLINE, retain=True)
                    await self._stopping.wait()
            except MqttError as err:
                self.connected = False
                self.last_error = str(err)
                _LOGGER.warning("MQTT error: %s (retrying in %ss)", err, RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)
            finally:
                self._client = None
                self.connected = False

    async def publish_json(
        self, topic: str, payload: dict[str, Any], *, retain: bool = True
    ) -> bool:
        return await self.publish(topic, json.dumps(payload), retain=retain)

    async def publish(self, topic: str, payload: str, *, retain: bool = False) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            await client.publish(topic, payload, retain=retain)
            return True
        except MqttError as err:
            _LOGGER.debug("Publish failed on %s: %s", topic, err)
            return False

    async def publish_discovery(self, version: str) -> None:
        """Announce the app entity; retained so it survives a restart."""
        from .discovery import build_health_config

        await self.publish_json(health_config_topic(), build_health_config(version))
