"""Build the option lists shown in the configuration form.

Pure Python: it only reads attributes from the state objects it is given, so it
can be tested without Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class _State(Protocol):
    """Structural view of a Home Assistant state, read-only on purpose."""

    @property
    def entity_id(self) -> str: ...

    @property
    def state(self) -> str: ...

    @property
    def attributes(self) -> dict[str, Any]: ...


#: Option carried by every 6-order pilot wire module (NodOn SIN-4-FP-21).
FIL_PILOTE_MARKER = "frost_protection"

NOT_FOUND = "introuvable"
OUT_OF_FILTER = "hors filtre"


def _friendly(state: _State) -> str:
    name = state.attributes.get("friendly_name")
    return str(name) if name else state.entity_id


def _label(state: _State) -> str:
    return f"{_friendly(state)} ({state.entity_id})"


def _finalise(
    options: list[tuple[str, str]], states: Mapping[str, _State], current: str | None
) -> list[tuple[str, str]]:
    """Keep the currently configured value even when it does not match."""
    options.sort(key=lambda item: item[1].lower())
    if not current:
        return options

    if any(value == current for value, _label in options):
        return options

    state = states.get(current)
    suffix = OUT_OF_FILTER if state is not None else NOT_FOUND
    label = f"{_label(state)} ({suffix})" if state is not None else f"{current} ({suffix})"
    return [(current, label), *options]


def pick_options(
    states: Mapping[str, _State],
    *,
    domain: str,
    device_class: str | None = None,
    current: str | None = None,
) -> list[tuple[str, str]]:
    """``(entity_id, label)`` options for one field.

    Filters on the domain and, when asked, on ``device_class``. If the filter
    matches nothing, every entity of the domain is offered instead: a template
    sensor without a device class must remain selectable.
    """
    prefix = f"{domain}."
    candidates = [
        state
        for entity_id, state in states.items()
        if entity_id.startswith(prefix)
        and (device_class is None or state.attributes.get("device_class") == device_class)
    ]

    if not candidates and device_class is not None:
        return pick_options(states, domain=domain, current=current)

    return _finalise([(state.entity_id, _label(state)) for state in candidates], states, current)


def pick_fil_pilote(
    states: Mapping[str, _State], current: str | None = None
) -> list[tuple[str, str]]:
    """Only the selects that look like a 6-order pilot wire module."""
    candidates = [
        state
        for entity_id, state in states.items()
        if entity_id.startswith("select.")
        and FIL_PILOTE_MARKER in (state.attributes.get("options") or [])
    ]

    if not candidates:
        return pick_options(states, domain="select", current=current)

    return _finalise([(state.entity_id, _label(state)) for state in candidates], states, current)


def pick_by_domain(
    states: Mapping[str, _State], domain: str, current: str | None = None
) -> list[tuple[str, str]]:
    """All entities of a domain (switches, weather, input_boolean…)."""
    return pick_options(states, domain=domain, current=current)
