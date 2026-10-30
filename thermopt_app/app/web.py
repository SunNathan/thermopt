"""Ingress web interface.

Home Assistant proxies the requests and handles authentication, so the app
must not implement a login. It must only accept connections from the
Supervisor, and it must use relative URLs: the ingress path changes per
installation and is given by the ``X-Ingress-Path`` header.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape
from thermopt_lib.core.orders import LABELS_FR, order_from_z2m
from thermopt_lib.perception.comfort import SLOT_DAY, SLOT_EVENING, SLOT_MORNING, SLOT_NIGHT

from .audit import audit
from .config import AppConfig, RoomConfig, ladder_rows, profile_summary, validate
from .ha import EntityState
from .history import HistoryStore, to_csv
from .loop import SupervisionLoop
from .model import ModelParameters
from .model import fit as fit_model
from .pickers import pick_by_domain, pick_fil_pilote, pick_options

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_IP = "172.30.32.2"
INGRESS_PORT = 8099
# Under ingress an absolute "/" would send the browser to Home Assistant.
# A relative target resolves against the current request URI instead.
REDIRECT_HOME = "./"
SLOT_LABELS = {
    SLOT_NIGHT: "Nuit",
    SLOT_MORNING: "Matin",
    SLOT_DAY: "Journée",
    SLOT_EVENING: "Soirée",
}
SLOTS = (SLOT_NIGHT, SLOT_MORNING, SLOT_DAY, SLOT_EVENING)

#: Entities created by the legacy integration, never by this app.
INTEGRATION_SIGNATURE = (
    "sensor.thermopt_prochain_cycle",
    "sensor.thermopt_temperature_exterieure",
    "sensor.thermopt_pieces",
    "binary_sensor.thermopt_pilotage_actif",
    "button.thermopt_generer_la_vue",
)


class WebRuntime:
    """State shared between the loop, the publisher and the pages."""

    def __init__(self, version: str, config: AppConfig) -> None:
        self.version = version
        self.started_at = datetime.now()
        self.config = config
        self.loop: SupervisionLoop | None = None
        self.states: dict[str, EntityState] = {}
        self.ha_version = "?"
        self.ha_location = ""
        self.mqtt_connected = False
        self.mqtt_detail = "en attente"
        self.healthy = False
        self.save_config = None  # set by main.py
        self.history: HistoryStore | None = None
        self.models: dict[str, ModelParameters] = {}
        self.save_models = None  # set by main.py

    # -- derived values used by the templates --------------------------------
    @property
    def fallback_active(self) -> bool:
        state = self.states.get(self.config.fallback_entity)
        return state is not None and state.state.lower() == "on"

    @property
    def outdoor_temperature(self) -> float | None:
        """Current outdoor temperature, straight from the weather entity."""
        entity = self.config.weather_entity
        if not entity:
            return None
        state = self.states.get(entity)
        if state is None:
            return None
        raw = state.attributes.get("temperature")
        try:
            return float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def weather(self) -> dict[str, Any]:
        """Everything the dashboard weather card shows — current state only."""
        entity = self.config.weather_entity
        state = self.states.get(entity) if entity else None
        loop = self.loop
        return {
            "entity": entity,
            "state": state.state if state else None,
            "temperature": self.outdoor_temperature,
            "forecast_count": loop.forecast_count if loop else 0,
            "forecast_error": loop.forecast_error if loop else None,
        }

    @property
    def supervisor_markers(self) -> list[str]:
        """Entities only the legacy integration creates, and still available."""
        markers: list[str] = []
        for entity_id in INTEGRATION_SIGNATURE:
            state = self.states.get(entity_id)
            if state is not None and state.available:
                markers.append(entity_id)
        return markers

    @property
    def integration_present(self) -> bool:
        return bool(self.supervisor_markers) and not self.config.supervisor_ack

    def rooms(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        predictions: dict[str, float | None] = {}
        if self.loop is not None and self.loop.last_snapshot is not None:
            predictions = {state.id: state.prediction for state in self.loop.last_snapshot.rooms}

        for room in self.config.rooms:
            live = self.states.get(room.temp_entity or "")
            power = self.states.get(room.power_entity or "")
            order = self.states.get(room.fil_pilote_entity or "")
            runtime = self.loop.rooms.get(room.id) if self.loop else None
            rows.append(
                {
                    "id": room.id,
                    "name": room.name,
                    "temperature": live.state if live else None,
                    "power": power.state if power else None,
                    "order": order.state if order else None,
                    "order_label": (LABELS_FR.get(order_from_z2m(order.state)) if order else None),
                    "safety": runtime.safety.value if runtime else "inactif",
                    "safety_reason": runtime.safety_reason if runtime else "",
                    "target_min": runtime.target_min if runtime else None,
                    "prediction": predictions.get(room.id),
                }
            )
        return rows


def _guard(request: web.Request) -> None:
    peer = request.remote
    if peer not in (SUPERVISOR_IP, "127.0.0.1", "::1"):
        raise web.HTTPForbidden(text="ThermOpt n'accepte que les requêtes du Supervisor")


def create_app(runtime: WebRuntime) -> web.Application:
    templates = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def render(name: str, **context: Any) -> web.Response:
        page = templates.get_template(name).render(runtime=runtime, slots=SLOTS, **context)
        return web.Response(text=page, content_type="text/html")

    # -- pages ---------------------------------------------------------------
    async def index(request: web.Request) -> web.Response:
        _guard(request)
        return render(
            "dashboard.html",
            active="dashboard",
            rooms=runtime.rooms(),
            ladder=ladder_rows(runtime.config),
            cycle=runtime.loop.last_cycle if runtime.loop else None,
            degraded=runtime.loop.degraded if runtime.loop else [],
            mode=runtime.loop.mode if runtime.loop else "observation",
            weather=runtime.weather(),
            markers=runtime.supervisor_markers,
        )

    async def acknowledge(request: web.Request) -> web.Response:
        _guard(request)
        runtime.config = replace(runtime.config, supervisor_ack=True)
        if runtime.save_config is not None:
            runtime.save_config(runtime.config)
        raise web.HTTPFound(REDIRECT_HOME)

    async def config_page(request: web.Request) -> web.Response:
        _guard(request)
        return _render_config()

    def _render_config(
        *,
        rooms: tuple[RoomConfig, ...] | None = None,
        config: AppConfig | None = None,
        errors: list[str] | None = None,
        message: str | None = None,
    ) -> web.Response:
        current = config or runtime.config
        selected = rooms if rooms is not None else current.rooms
        states = runtime.states

        rows = []
        for room in selected:
            rows.append(
                {
                    "room": room,
                    "temp": pick_options(
                        states,
                        domain="sensor",
                        device_class="temperature",
                        current=room.temp_entity,
                    ),
                    "humidity": pick_options(
                        states,
                        domain="sensor",
                        device_class="humidity",
                        current=room.humidity_entity,
                    ),
                    "power": pick_options(
                        states, domain="sensor", device_class="power", current=room.power_entity
                    ),
                    "energy": pick_options(
                        states, domain="sensor", device_class="energy", current=room.energy_entity
                    ),
                    "fil": pick_fil_pilote(states, room.fil_pilote_entity),
                    "relay": pick_by_domain(states, "switch", room.relay_entity),
                }
            )

        return render(
            "config.html",
            active="config",
            config=current,
            rows=rows,
            errors=errors or [],
            message=message,
            weather=pick_by_domain(states, "weather", current.weather_entity),
            booleans=pick_by_domain(states, "input_boolean", current.auto_entity),
            fallback_choices=pick_by_domain(states, "input_boolean", current.fallback_entity),
            slot_labels=SLOT_LABELS,
            summary=profile_summary(current),
            ladder=ladder_rows(current),
        )

    async def config_save(request: web.Request) -> web.Response:
        _guard(request)
        form = await request.post()

        rooms = _parse_rooms(form)

        target = form.get("delete_room")
        if target:
            rooms = tuple(room for room in rooms if room.id != str(target))
            return _render_config(
                rooms=rooms,
                message="Pièce retirée : enregistre pour appliquer.",
            )

        if form.get("action") == "add":
            rooms = (*rooms, RoomConfig.new())
            return _render_config(
                rooms=rooms,
                message="Pièce ajoutée : renseigne-la puis enregistre.",
            )

        candidate = _apply_form(runtime.config, form, rooms)
        errors = validate(candidate)
        if errors:
            return _render_config(config=candidate, errors=errors)

        runtime.config = candidate
        if runtime.save_config is not None:
            runtime.save_config(candidate)
        if runtime.loop is not None:
            runtime.loop.apply_config(candidate)

        raise web.HTTPFound(REDIRECT_HOME)

    async def toggle_active(request: web.Request) -> web.Response:
        _guard(request)
        runtime.config = replace(runtime.config, active=not runtime.config.active)
        if runtime.save_config is not None:
            runtime.save_config(runtime.config)
        if runtime.loop is not None:
            runtime.loop.apply_config(runtime.config)
        raise web.HTTPFound(REDIRECT_HOME)

    async def _history_rows() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if runtime.history is None:
            return rows
        for room in runtime.config.rooms:
            records = await runtime.history.async_read(room=room.id)
            rows.append(
                {
                    "id": room.id,
                    "name": room.name,
                    "report": audit(records, room.name),
                    "model": runtime.models.get(room.id),
                }
            )
        return rows

    async def history_page(request: web.Request) -> web.Response:
        _guard(request)
        return render(
            "history.html",
            active="history",
            rows=await _history_rows(),
            errors=[],
            message=None,
            size=runtime.history.size() if runtime.history else 0,
        )

    async def history_fit(request: web.Request) -> web.Response:
        _guard(request)
        rows = await _history_rows()
        errors: list[str] = []
        fitted: dict[str, ModelParameters] = {}

        if runtime.history is not None:
            for room in runtime.config.rooms:
                records = await runtime.history.async_read(room=room.id)
                report = audit(records, room.name)
                if not report.ok:
                    errors.extend(f"{room.name} : {item}" for item in report.missing)
                    continue
                params, problems = fit_model(records)
                if params is None:
                    errors.extend(f"{room.name} : {item}" for item in problems)
                else:
                    fitted[room.id] = params

        if fitted:
            runtime.models.update(fitted)
            if runtime.save_models is not None:
                runtime.save_models(runtime.models)
            if runtime.loop is not None:
                runtime.loop.models.update(fitted)

        rows = await _history_rows()
        return render(
            "history.html",
            active="history",
            rows=rows,
            errors=errors,
            message=(f"{len(fitted)} modèle(s) identifié(s)." if fitted else None),
            size=runtime.history.size() if runtime.history else 0,
        )

    async def history_export(request: web.Request) -> web.Response:
        _guard(request)
        if runtime.history is None:
            raise web.HTTPNotFound()
        records = await runtime.history.async_read()
        body = to_csv(records)
        return web.Response(
            text=body,
            content_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="thermopt-{datetime.now():%Y%m%d-%H%M}.csv"'
            },
        )

    async def health(request: web.Request) -> web.Response:
        status = 200 if runtime.healthy else 503
        return web.json_response(
            {
                "status": "ok" if runtime.healthy else "starting",
                "version": runtime.version,
                "mqtt": runtime.mqtt_connected,
            },
            status=status,
        )

    app = web.Application()
    app["runtime"] = runtime
    app.router.add_get("/", index)
    app.router.add_get("/config", config_page)
    app.router.add_post("/config", config_save)
    app.router.add_post("/active", toggle_active)
    app.router.add_post("/ack", acknowledge)
    app.router.add_get("/history", history_page)
    app.router.add_post("/history/fit", history_fit)
    app.router.add_get("/history/export.csv", history_export)
    app.router.add_get("/health", health)
    return app


# ---------------------------------------------------------------------------
# Form parsing
# ---------------------------------------------------------------------------
def _parse_rooms(form) -> tuple[RoomConfig, ...]:
    rooms: list[RoomConfig] = []
    index = 0
    while f"room_{index}_id" in form:
        rooms.append(
            RoomConfig(
                id=str(form.get(f"room_{index}_id", "")),
                name=str(form.get(f"room_{index}_name", "")).strip(),
                temp_entity=_clean(form.get(f"room_{index}_temp")),
                humidity_entity=_clean(form.get(f"room_{index}_humidity")),
                fil_pilote_entity=_clean(form.get(f"room_{index}_fil")),
                relay_entity=_clean(form.get(f"room_{index}_relay")),
                power_entity=_clean(form.get(f"room_{index}_power")),
                energy_entity=_clean(form.get(f"room_{index}_energy")),
            )
        )
        index += 1
    return tuple(rooms)


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _apply_form(base: AppConfig, form, rooms: tuple[RoomConfig, ...]) -> AppConfig:
    def number(key: str, default: float) -> float:
        try:
            return float(form.get(key, default))
        except (TypeError, ValueError):
            return default

    starts = {slot: str(form.get(f"start_{slot}", base.starts.get(slot, ""))) for slot in SLOTS}
    weekday = {slot: number(f"weekday_{slot}", base.weekday.get(slot, 19.0)) for slot in SLOTS}
    weekend = {slot: number(f"weekend_{slot}", base.weekend.get(slot, 19.0)) for slot in SLOTS}

    return AppConfig(
        rooms=rooms,
        weather_entity=_clean(form.get("weather_entity")) or base.weather_entity,
        auto_entity=_clean(form.get("auto_entity")),
        fallback_entity=_clean(form.get("fallback_entity")) or base.fallback_entity,
        hp_price=number("hp_price", base.hp_price),
        hc_price=number("hc_price", base.hc_price),
        hc_windows=str(form.get("hc_windows", base.hc_windows)),
        comfort_setpoint=number("comfort_setpoint", base.comfort_setpoint),
        frost_setpoint=number("frost_setpoint", base.frost_setpoint),
        active=form.get("active") == "on",
        starts=starts,
        weekday=weekday,
        weekend=weekend,
        present_day=number("present_day", base.present_day),
        tolerance=number("tolerance", base.tolerance),
        high_margin=number("high_margin", base.high_margin),
    )


async def start_site(runtime: WebRuntime) -> web.AppRunner:
    runner = web.AppRunner(create_app(runtime), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", INGRESS_PORT)
    await site.start()
    _LOGGER.info("Interface ingress à l'écoute sur %s", INGRESS_PORT)
    return runner
