"""Runtime configuration — small, deterministic, fail-safe.

Governs the crisis-card register (G4, Phase 2b) plus the Phase 6/7/8 knobs: the canonical
Active-File location (council D4), the Notion privacy dial (Phase 6), and the export/records
directories (council D6). Everything resolves at runtime and fails safe to its most
conservative default; a broken ``config.toml`` never breaks a turn.

Resolution order for each value (first wins):
    1. an environment variable (handy for a single session / tests)
    2. ``config.toml`` at the repo/install root
    3. the built-in default
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dr_alex import paths

#: The full hard-coded India crisis card (today's behavior) vs. the graded register that
#: renders a warmer variant for *passive* ideation only. Full is the default and the
#: safe fallback.
VALID_CRISIS_CARD_STYLES = ("full", "graded")

#: Notion privacy dial (council Phase 6). ``summary`` is the default and the RED fallback;
#: a raw transcript is NEVER an option at any level.
VALID_NOTION_DETAIL_LEVELS = ("summary", "structured", "full")

_ENV_CRISIS_CARD_STYLE = "DR_ALEX_CRISIS_CARD_STYLE"
_ENV_NOTION_DETAIL = "DR_ALEX_NOTION_DETAIL"
_ENV_ACTIVE_FILE = "DR_ALEX_ACTIVE_FILE"
_ENV_RECORDS_DIR = "DR_ALEX_RECORDS_DIR"
_ENV_EXPORTS_DIR = "DR_ALEX_EXPORTS_DIR"


@dataclass(frozen=True)
class Config:
    crisis_card_style: str = "full"
    notion_detail_level: str = "summary"


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


def _section(toml: dict, name: str) -> dict:
    sec = toml.get(name)
    return sec if isinstance(sec, dict) else {}


def _coerce_style(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_CRISIS_CARD_STYLES:
        return value.strip().lower()
    return "full"  # fail safe to the full card


def _coerce_detail(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() in VALID_NOTION_DETAIL_LEVELS:
        return value.strip().lower()
    return "summary"  # fail safe to the least-detailed mirror


def load_config() -> Config:
    """Resolve the effective config. Cheap; safe to call per-turn."""
    toml = _load_toml()

    env_style = os.environ.get(_ENV_CRISIS_CARD_STYLE)
    if env_style is not None:
        style = _coerce_style(env_style)
    else:
        style = _coerce_style(_section(toml, "safety").get("crisis_card_style", "full"))

    env_detail = os.environ.get(_ENV_NOTION_DETAIL)
    if env_detail is not None:
        detail = _coerce_detail(env_detail)
    else:
        detail = _coerce_detail(_section(toml, "notion").get("detail_level", "summary"))

    return Config(crisis_card_style=style, notion_detail_level=detail)


def crisis_card_style() -> str:
    """The effective crisis-card style, ``"full"`` (default) or ``"graded"``."""
    return load_config().crisis_card_style


def notion_detail_level() -> str:
    """The effective Notion mirror detail: ``summary`` (default) | ``structured`` | ``full``."""
    return load_config().notion_detail_level


# ---------------------------------------------------------------------------
# Canonical record + export/records directories (council D4 + D6).
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    # dr_alex/config.py → dr_alex → repo root
    return Path(__file__).resolve().parent.parent


def _default_records_dir() -> Path:
    # Default lives alongside the install (``~/dr-alex/records`` when run from source, which is
    # exactly ``$HOME/dr-alex``). records/ is gitignored + 0700 (council D4 rider 1).
    #
    # PraxVault migration (one line, for when the encrypted vault exists on this Mac):
    #   set ``[records] active_file`` in config.toml to e.g.
    #   "~/Library/Mobile Documents/.../PraxVault/DrAlex/Active-File.md" — the exporters and the
    #   Notion mirror all read the configured path, so nothing else changes (council D4 rider 3).
    return _repo_root() / "records"


def records_dir() -> Path:
    """The 0700 directory holding the canonical Active File (council D4)."""
    env = os.environ.get(_ENV_RECORDS_DIR)
    if env:
        return Path(env).expanduser()
    toml = _load_toml()
    val = _section(toml, "records").get("dir")
    if isinstance(val, str) and val.strip():
        return Path(val).expanduser()
    return _default_records_dir()


def active_file_path() -> Path:
    """Absolute path to the canonical, human-readable local record (council D4).

    Default: ``<records_dir>/Active-File.md``. Overridable via ``DR_ALEX_ACTIVE_FILE`` or
    ``[records] active_file`` in config.toml (the documented PraxVault migration point).
    """
    env = os.environ.get(_ENV_ACTIVE_FILE)
    if env:
        return Path(env).expanduser()
    toml = _load_toml()
    val = _section(toml, "records").get("active_file")
    if isinstance(val, str) and val.strip():
        return Path(val).expanduser()
    return records_dir() / "Active-File.md"


def exports_dir() -> Path:
    """The 0700 directory holding date-ranged exports (council D6). Default ``<repo>/exports``."""
    env = os.environ.get(_ENV_EXPORTS_DIR)
    if env:
        return Path(env).expanduser()
    toml = _load_toml()
    val = _section(toml, "exports").get("dir")
    if isinstance(val, str) and val.strip():
        return Path(val).expanduser()
    return _repo_root() / "exports"
