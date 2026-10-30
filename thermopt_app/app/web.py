"""Ingress web interface.

Home Assistant proxies the requests and handles authentication, so the app
must not implement a login. It must only accept connections from the
Supervisor, and it must use relative URLs: the ingress path changes per
installation and is given by the ``X-Ingress-Path`` header.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp import web

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_IP = "172.30.32.2"
INGRESS_PORT = 8099

PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ThermOpt</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 24px; line-height: 1.5;
    background: #fafafa; color: #1c1c1c;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #111418; color: #e8eaed; }}
    .card {{ background: #1b1f24 !important; border-color: #2a3038 !important; }}
    .muted {{ color: #9aa4b2 !important; }}
  }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .muted {{ color: #5f6b7a; font-size: 0.9rem; }}
  .cards {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); margin-top: 24px; }}
  .card {{ background: #fff; border: 1px solid #e3e7ec; border-radius: 12px; padding: 16px; }}
  .card h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: .04em; margin: 0 0 8px; color: #5f6b7a; }}
  .value {{ font-size: 1.6rem; font-weight: 600; }}
  .ok {{ color: #2e7d32; }}
  .ko {{ color: #c62828; }}
  code {{ background: rgba(127,127,127,.15); padding: 1px 5px; border-radius: 4px; }}
  footer {{ margin-top: 32px; font-size: .85rem; }}
</style>
</head>
<body>
  <h1>ThermOpt</h1>
  <div class="muted">Supervision du chauffage fil pilote — {version}</div>

  <div class="cards">
    <div class="card">
      <h2>Application</h2>
      <div class="value {app_class}">{app_state}</div>
      <div class="muted">démarrée {uptime}</div>
    </div>
    <div class="card">
      <h2>Home Assistant</h2>
      <div class="value">{ha_version}</div>
      <div class="muted">{ha_location}</div>
    </div>
    <div class="card">
      <h2>MQTT</h2>
      <div class="value {mqtt_class}">{mqtt_state}</div>
      <div class="muted">{mqtt_detail}</div>
    </div>
  </div>

  <footer class="muted">
    Phase A : la chaîne de livraison est validée. La configuration des pièces et
    les garde-fous arrivent aux phases suivantes.<br>
    Cette page est servie par l'app via <code>ingress</code> : aucun port n'est
    exposé, et Home Assistant gère l'authentification.
  </footer>
</body>
</html>
"""


class WebRuntime:
    """State the page reads, filled by the main loop."""

    def __init__(self, version: str) -> None:
        self.version = version
        self.started_at = datetime.now()
        self.ha_version = "?"
        self.ha_location = "?"
        self.mqtt_connected = False
        self.mqtt_detail = "en attente"
        self.healthy = False


def _guard(request: web.Request) -> None:
    """Only the Supervisor may reach us (see the ingress documentation)."""
    peer = request.remote
    if peer not in (SUPERVISOR_IP, "127.0.0.1", "::1"):
        raise web.HTTPForbidden(text="ThermOpt only accepts requests from the Supervisor")


def _uptime(runtime: WebRuntime) -> str:
    delta = datetime.now() - runtime.started_at
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"depuis {minutes} min"
    return f"depuis {minutes // 60} h {minutes % 60:02d}"


async def index(request: web.Request) -> web.Response:
    _guard(request)
    runtime: WebRuntime = request.app["runtime"]

    html = PAGE.format(
        version=runtime.version,
        app_state="Opérationnelle" if runtime.healthy else "Démarrage",
        app_class="ok" if runtime.healthy else "ko",
        uptime=_uptime(runtime),
        ha_version=runtime.ha_version,
        ha_location=runtime.ha_location,
        mqtt_state="Connecté" if runtime.mqtt_connected else "Hors ligne",
        mqtt_class="ok" if runtime.mqtt_connected else "ko",
        mqtt_detail=runtime.mqtt_detail,
    )
    return web.Response(text=html, content_type="text/html")


async def health(request: web.Request) -> web.Response:
    runtime: WebRuntime = request.app["runtime"]
    status = 200 if runtime.healthy else 503
    return web.json_response(
        {
            "status": "ok" if runtime.healthy else "starting",
            "version": runtime.version,
            "mqtt": runtime.mqtt_connected,
        },
        status=status,
    )


def create_app(runtime: WebRuntime) -> web.Application:
    app = web.Application()
    app["runtime"] = runtime
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    return app


async def start_site(runtime: WebRuntime) -> web.AppRunner:
    runner = web.AppRunner(create_app(runtime), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", INGRESS_PORT)
    await site.start()
    _LOGGER.info("Ingress interface listening on %s", INGRESS_PORT)
    return runner


__all__: list[Any] = ["WebRuntime", "create_app", "start_site"]
