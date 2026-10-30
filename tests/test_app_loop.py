"""Tests for the supervision loop's mode handling."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC

from app.config import AppConfig
from app.loop import SupervisionLoop


class _Ha:
    """Minimal stand-in: the mode logic only reads the state cache."""

    def __init__(self, states: dict | None = None) -> None:
        self._states = states or {}

    def cached(self) -> dict:
        return self._states


def _loop(config: AppConfig, states: dict | None = None) -> SupervisionLoop:
    return SupervisionLoop(_Ha(states), None, config, UTC, None)  # type: ignore[arg-type]


def test_mode_is_actif_when_enabled() -> None:
    loop = _loop(AppConfig(active=True))
    loop.refresh_mode()
    assert loop.mode == "actif"


def test_mode_follows_the_configuration_immediately() -> None:
    """Pressing "observation" must not wait for the next cycle."""
    loop = _loop(AppConfig(active=True))
    loop.refresh_mode()
    assert loop.mode == "actif"

    loop.apply_config(replace(loop._config, active=False))
    assert loop.mode == "observation"

    loop.apply_config(replace(loop._config, active=True))
    assert loop.mode == "actif"


def test_mode_reports_the_fallback() -> None:
    from app.ha import EntityState

    states = {"input_boolean.thermopt_repli": EntityState("input_boolean.thermopt_repli", "on", {})}
    loop = _loop(AppConfig(active=True), states)
    loop.refresh_mode()
    assert loop.mode == "repli"


def test_observation_wins_over_the_fallback() -> None:
    from app.ha import EntityState

    states = {"input_boolean.thermopt_repli": EntityState("input_boolean.thermopt_repli", "on", {})}
    loop = _loop(AppConfig(active=False), states)
    loop.refresh_mode()
    assert loop.mode == "observation"
