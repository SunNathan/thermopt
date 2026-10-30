"""Thin client for the Supervisor and Home Assistant Core APIs.

Every app gets ``SUPERVISOR_TOKEN`` in its environment. ``http://supervisor``
is the Supervisor itself, ``http://supervisor/core/api`` is Home Assistant's
REST API, proxied with administrator rights.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
REQUEST_TIMEOUT = ClientTimeout(total=20)


class SupervisorError(RuntimeError):
    """Raised when the Supervisor answers with an error."""


@dataclass(frozen=True, slots=True)
class MqttCredentials:
    """Broker details provided by the Supervisor."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    ssl: bool = False


class SupervisorClient:
    """Minimal async client, enough for milestone A."""

    def __init__(self, token: str | None = None, session: ClientSession | None = None) -> None:
        self._token = token or os.environ.get("SUPERVISOR_TOKEN", "")
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> SupervisorClient:
        if self._session is None:
            self._session = ClientSession(timeout=REQUEST_TIMEOUT)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise SupervisorError("client not opened")
        return self._session

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, url: str) -> object:
        for attempt in range(2):
            try:
                async with self.session.get(url, headers=self.headers) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise SupervisorError(f"{url} -> {response.status}: {body[:200]}")
                    return await response.json()
            except (TimeoutError, ClientError) as err:
                if attempt == 1:
                    raise SupervisorError(f"{url} unreachable: {err}") from err
                _LOGGER.debug("Retrying %s after %s", url, err)
                await asyncio.sleep(2)
        raise SupervisorError(f"{url} unreachable")

    async def core_config(self) -> dict:
        """Home Assistant version and metadata (proves the proxy works)."""
        payload = await self._get(f"{SUPERVISOR_URL}/core/api/config")
        if not isinstance(payload, dict):
            raise SupervisorError("unexpected /core/api/config payload")
        return payload

    async def mqtt_service(self) -> MqttCredentials:
        """Broker credentials granted by ``services: [mqtt:want]``."""
        payload = await self._get(f"{SUPERVISOR_URL}/services/mqtt")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise SupervisorError("MQTT service not available")
        return MqttCredentials(
            host=str(data.get("host") or "core-mosquitto"),
            port=int(data.get("port") or 1883),
            username=data.get("username"),
            password=data.get("password"),
            ssl=bool(data.get("ssl", False)),
        )
