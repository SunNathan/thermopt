"""Build a Lovelace view from the real entity registry.

Entity ids depend on the room name chosen by the user, so a shipped YAML file
cannot hardcode them. This module walks the registry instead: every entity is
looked up through its device and its ``unique_id`` suffix, which is stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry

from .const import DOMAIN
from .runtime import ThermOptRuntime

# unique_id suffix -> (label in the generated card, icon)
ROOM_ORDER = (
    ("temperature", "Température"),
    ("target_min", "Consigne minimale"),
    ("target_max", "Consigne maximale"),
    ("requested_order", "Ordre demandé"),
    ("applied_order", "Ordre appliqué"),
    ("safety", "Sécurité"),
    ("slot", "Créneau"),
    ("power", "Puissance"),
    ("energy", "Énergie"),
)

SYSTEM_ORDER = (
    ("pilotage_actif", "Pilotage"),
    ("status", "Mode"),
    ("degraded", "Santé"),
    ("heures_creuses", "Tarif"),
    ("price", "Prix"),
    ("last_cycle", "Cycle"),
)


@dataclass(slots=True)
class DashboardData:
    """Collected entity ids, plus what is missing."""

    system: dict[str, str] = field(default_factory=dict)
    rooms: dict[str, dict[str, str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def _entities_of_device(hass: HomeAssistant, identifiers: set[tuple[str, str]]) -> dict[str, str]:
    """Map ``unique_id`` suffix -> ``entity_id`` for one device."""
    devices = device_registry.async_get(hass)
    device = devices.async_get_device(identifiers=identifiers)
    if device is None:
        return {}

    entries = entity_registry.async_get(hass)
    prefix = f"{next(iter(identifiers))[1]}_"
    found: dict[str, str] = {}
    for entry in entity_registry.async_entries_for_device(entries, device.id):
        unique_id = entry.unique_id or ""
        if unique_id.startswith(prefix):
            found[unique_id[len(prefix) :]] = entry.entity_id
    return found


def collect(hass: HomeAssistant, runtime: ThermOptRuntime) -> DashboardData:
    """Gather system and per-room entity ids."""
    entry_id = runtime.entry.entry_id
    data = DashboardData()

    data.system = _entities_of_device(hass, {(DOMAIN, entry_id)})
    for key, _label in SYSTEM_ORDER:
        if key not in data.system:
            data.missing.append(f"systeme: {key}")

    for room in runtime.rooms.values():
        entities = _entities_of_device(hass, {(DOMAIN, f"{entry_id}_{room.config.subentry_id}")})
        data.rooms[room.config.name] = entities
        for key, _label in ROOM_ORDER:
            if key not in entities:
                data.missing.append(f"{room.config.name}: {key}")

    return data


def build_dashboard_yaml(data: DashboardData) -> str:
    """Render a paste-ready Lovelace dashboard using the real entity ids.

    The output is a *complete* dashboard (``title`` + ``views``), not a bare
    view: pasting a list where Home Assistant expects an object is the mistake
    that produced "Expected an object, but received: [object Object]".
    """
    lines: list[str] = [
        "title: ThermOpt",
        "views:",
        "  - title: ThermOpt",
        "    path: thermopt",
        "    icon: mdi:home-thermometer",
        "    cards:",
    ]

    status = data.system.get("status", "")
    last_command = data.system.get("last_command", "")
    lines += [
        "      - type: markdown",
        "        content: |",
        "          {% set actif = state_attr('" + status + "', 'pilotage_actif') %}",
        "          {% set portee = state_attr('" + status + "', 'portee') %}",
        "          {% if actif and portee == 'optimiseur' %}",
        "          ## 🟢 Pilotage complet",
        "",
        "          ThermOpt optimise les ordres selon le tarif et la météo.",
        "          {% elif actif %}",
        "          ## 🟡 Sécurité seule",
        "",
        "          ThermOpt n'envoie un ordre que si une pièce passe sous sa borne de",
        "          confort. L'optimisation arrivera plus tard.",
        "",
        "          {{ state_attr('" + status + "', 'raison') }}",
        "          {% else %}",
        "          ## ⚪ Pilotage inactif",
        "",
        "          **Aucun ordre n'est envoyé aux radiateurs.**",
        "",
        "          {{ state_attr('" + status + "', 'raison') }}",
        "          {% endif %}",
        "",
        "          Mode : **{{ states('"
        + status
        + "') }}** · Dernière commande : **{{ states('"
        + last_command
        + "') }}**",
    ]

    glance = [
        ("pilotage_actif", "Pilotage"),
        ("status", "Mode"),
        ("degraded", "Santé"),
        ("heures_creuses", "Tarif"),
        ("price", "Prix"),
        ("last_cycle", "Cycle"),
    ]
    lines += [
        "      - type: glance",
        "        title: Superviseur",
        "        columns: 3",
        "        entities:",
    ]
    for key, label in glance:
        if key in data.system:
            lines += [f"          - entity: {data.system[key]}", f"            name: {label}"]

    for room_name, entities in data.rooms.items():
        lines += [
            "      - type: entities",
            f"        title: {room_name}",
            "        show_header_toggle: false",
            "        entities:",
        ]
        for key, label in ROOM_ORDER:
            if key in entities:
                lines += [f"          - entity: {entities[key]}", f"            name: {label}"]

    degraded = data.system.get("degraded")
    if degraded:
        lines += [
            "      - type: conditional",
            "        conditions:",
            f"          - entity: {degraded}",
            '            state: "on"',
            "        card:",
            "          type: markdown",
            "          content: |",
            "            ## ⚠️ Situation dégradée",
            "",
            "            {% for line in state_attr('" + degraded + "', 'details') or [] %}",
            "            - {{ line }}",
            "            {% endfor %}",
        ]

    return "\n".join(lines) + "\n"


def validate_dashboard_yaml(text: str) -> str | None:
    """Parse the generated YAML; return an error message or ``None``."""
    import yaml

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as err:
        return f"YAML invalide : {err}"

    if not isinstance(parsed, dict) or "views" not in parsed:
        return "Le YAML généré n'est pas un tableau de bord (clé 'views' absente)."
    return None


def summary(data: DashboardData) -> str:
    """Short status line for the notification body."""
    rooms = ", ".join(data.rooms) or "aucune"
    text = f"{len(data.rooms)} pièce(s) : {rooms}."
    if data.missing:
        text += "\n\nEntités manquantes :\n" + "\n".join(f"- {item}" for item in data.missing)
    return text
