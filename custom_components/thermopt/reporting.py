"""Human-readable explanations for degradation flags.

Pure Python: no Home Assistant imports. Numbers are formatted the French way,
and every message says what to do about it.
"""

from __future__ import annotations

from .const import (
    DEGRADED_ACTUATOR_UNAVAILABLE,
    DEGRADED_NO_EFFECT,
    DEGRADED_NO_ROOM,
    DEGRADED_PROFILE_UNREACHABLE,
    DEGRADED_RELAY_OFF,
    DEGRADED_SENSOR_FROZEN,
    DEGRADED_SENSOR_MISSING,
    DEGRADED_TARIFF_MISMATCH,
    DEGRADED_WEATHER,
)
from .core.orders import Order


def fmt(value: float, digits: int = 1) -> str:
    """Format a number the French way: 20.5 -> ``20,5``."""
    return f"{value:.{digits}f}".replace(".", ",")


def describe_profile_issue(issue: str, ladder) -> str:
    """Turn a ``profile_issues`` key into an actionable sentence.

    ``issue`` looks like ``unreachable:22.0`` or ``eco_below_floor:17.0``.
    """
    kind, _, raw = issue.partition(":")
    try:
        target = float(raw)
    except ValueError:
        return issue

    eco = ladder.setpoint(Order.ECO)
    comfort = ladder.comfort

    if kind == "eco_below_floor":
        return (
            f"Eco ({fmt(eco)} °C) est plus froid que ta borne de confort "
            f"({fmt(target)} °C). Le garde-fou forcerait Confort chaque nuit. "
            f"Passe la consigne Confort du radiateur à {fmt(target + 3.5)} °C, "
            f"ou abaisse la cible de nuit à {fmt(eco)} °C."
        )

    if kind == "unreachable":
        return (
            f"Ta cible de {fmt(target)} °C n'est atteignable par aucun ordre "
            f"(Confort {fmt(comfort)} °C, Eco {fmt(eco)} °C). "
            "Rapproche-la de l'échelle des ordres."
        )

    return issue


def describe_reason(
    reason: str,
    *,
    ladder=None,
    room: str | None = None,
    issue: str | None = None,
) -> str:
    """One sentence per degradation flag."""
    who = f"Pièce « {room} » : " if room else ""

    if reason == DEGRADED_WEATHER:
        return (
            "Prévision météo indisponible : ThermOpt utilise la dernière valeur "
            "connue (ou une sinusoïde journalière)."
        )
    if reason == DEGRADED_NO_ROOM:
        return (
            "Aucune pièce n'est configurée : ajoute une pièce sur la carte de "
            "l'intégration ThermOpt."
        )
    if reason == DEGRADED_PROFILE_UNREACHABLE:
        if issue and ladder is not None:
            return describe_profile_issue(issue, ladder)
        return "Ton profil de confort n'est pas cohérent avec la consigne Confort du radiateur."
    if reason == DEGRADED_SENSOR_MISSING:
        return f"{who}capteur de température absent ou indisponible."
    if reason == DEGRADED_SENSOR_FROZEN:
        return (
            f"{who}capteur figé (variation < 0,05 °C sur 45 min). "
            "Vérifie la pile ou le maillage Zigbee."
        )
    if reason == DEGRADED_ACTUATOR_UNAVAILABLE:
        return f"{who}module fil pilote injoignable (entité indisponible)."
    if reason == DEGRADED_RELAY_OFF:
        return (
            f"{who}le relais du module était coupé, donc le radiateur ne "
            "pouvait pas chauffer. ThermOpt l'a remis en marche."
        )
    if reason == DEGRADED_TARIFF_MISMATCH:
        return (
            "Le signal Heures Creuses réel ne correspond pas au planning "
            "configuré. Le planning fait foi ; vérifie tes plages."
        )
    if reason == DEGRADED_NO_EFFECT:
        return (
            f"{who}l'ordre a été appliqué mais le radiateur ne consomme pas de "
            "puissance alors que la pièce est sous sa consigne. Vérifie le "
            "relais, le câblage fil pilote et le mode local du radiateur."
        )
    return reason
