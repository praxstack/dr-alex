"""Runtime configuration — small, deterministic, fail-safe.

Currently governs one thing: the crisis-card register (G4). The default is and must
remain ``"full"`` — the current, byte-for-byte crisis card — so nothing about the RED
path changes until Prax and Shreya deliberately opt in (council open question Q2).

Resolution order (first wins):
    1. env ``DR_ALEX_CRISIS_CARD_STYLE`` (handy for a single session / tests)
    2. ``config.toml`` at the repo/install root, ``[safety] crisis_card_style``
    3. the built-in default, ``"full"``

Any unrecognized value fails safe to ``"full"`` (never silently to the warmer variant).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

from dr_alex import paths

#: The full hard-coded India crisis card (today's behavior) vs. the graded register that
#: renders a warmer variant for *passive* ideation only. Full is the default and the
#: safe fallback.
VALID_CRISIS_CARD_STYLES = ("full", "graded")

_ENV_CRISIS_CARD_STYLE = "DR_ALEX_CRISIS_CARD_STYLE"


@dataclass(frozen=True)
class Config:
    crisis_card_style: str = "full"


def _load_toml() -> dict:
    p = paths.find("config.toml")
    if p is None:
        return {}
    try:
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):  # a broken config must never break a turn
        return {}


def _coerce_style(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_CRISIS_CARD_STYLES:
        return value.strip().lower()
    return "full"  # fail safe to the full card


def load_config() -> Config:
    """Resolve the effective config. Cheap; safe to call per-turn."""
    env = os.environ.get(_ENV_CRISIS_CARD_STYLE)
    if env is not None:
        return Config(crisis_card_style=_coerce_style(env))

    toml = _load_toml()
    safety = toml.get("safety", {}) if isinstance(toml.get("safety"), dict) else {}
    return Config(crisis_card_style=_coerce_style(safety.get("crisis_card_style", "full")))


def crisis_card_style() -> str:
    """The effective crisis-card style, ``"full"`` (default) or ``"graded"``."""
    return load_config().crisis_card_style
