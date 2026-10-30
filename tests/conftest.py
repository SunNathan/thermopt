"""Test bootstrap.

Three concerns are handled here:

1. ``core`` and ``perception`` are pure packages living inside the integration
   directory. They are put on ``sys.path`` so unit tests can import them
   without triggering the Home Assistant side of the component.
2. Home Assistant's loader scans ``<config_dir>/custom_components``. Tests get
   a throw-away config dir containing a copy of ``custom_components``, so
   nothing is ever written inside the repository.
3. ``pytest-homeassistant-custom-component`` disables sockets before every
   test, which is impossible on Windows: asyncio's ProactorEventLoop itself
   needs a socket. The guard is neutralised on that platform only.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = ROOT / "custom_components" / "thermopt"

for path in (str(ROOT), str(INTEGRATION_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":  # pragma: no cover - platform specific
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None  # type: ignore[assignment]


@pytest.fixture
def weather_service(hass):
    """Register a weather forecast service returning hourly data."""
    from datetime import timedelta

    from homeassistant.core import ServiceCall, SupportsResponse
    from homeassistant.util import dt as dt_util

    async def _get_forecasts(call: ServiceCall) -> dict:
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        return {
            call.data["entity_id"]: {
                "forecast": [
                    {
                        "datetime": (now + timedelta(hours=hour)).isoformat(),
                        "temperature": 6.0 - hour * 0.2,
                    }
                    for hour in range(24)
                ]
            }
        }

    hass.services.async_register(
        "weather",
        "get_forecasts",
        _get_forecasts,
        supports_response=SupportsResponse.ONLY,
    )


@pytest.fixture(scope="session")
def _config_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Config dir containing a copy of the integration."""
    target = tmp_path_factory.mktemp("thermopt_config")
    shutil.copytree(ROOT / "custom_components", target / "custom_components")
    return str(target)


@pytest.fixture
def config_dir(_config_dir: str) -> str:
    """Point the Home Assistant test harness at our throw-away config dir."""
    return _config_dir


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the copied integration discoverable by the loader."""
    yield
