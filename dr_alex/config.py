"""Runtime configuration — small, deterministic, fail-safe.

Governs the crisis-card register (G4, Phase 2b) plus the Phase 6/7/8 knobs: the canonical
Active-File location (council D4), the Notion privacy dial (Phase 6), and the export/records
directories (council D6). Everything resolves at runtime and fails safe to its most
conservative default; a broken ``config.toml`` never breaks a turn.

Resolution order for each value (first wins):
    1. an environment variable (handy for a single session / tests)
    2. ``config.toml`` at the repo/install root
    3. the built-in default

Central environment-variable reference (single source of truth — every ``DR_ALEX_*`` var
lives here so operators and the self-improve loop share one map). All boolean switches read
truthy as one of ``1/true/yes/on`` (case-insensitive); anything else is falsy.

PRIVACY KILL-SWITCHES (set truthy to disable a subsystem; each fails safe to OFF/degraded):
    DR_ALEX_TELEMETRY_OFF   Disable the entire ``state.db`` telemetry store. Every read/write
                            degrades to a no-op/empty result — no mood chips, traces, or
                            transcripts are persisted. (statedb.telemetry_enabled)
    DR_ALEX_MEMORY_OFF      Disable the durable memory store — degrade to Phase-2 behaviour
                            (no recall, no session-end remember/scrub). (memstore.memory_enabled)
    DR_ALEX_NOTION_OFF      Disable the Notion mirror. Note: Notion is OPT-IN — this var only
                            forces it off; ``is_enabled`` also requires config + a token.
                            (notion)
    DR_ALEX_VOICE_OFF       Disable local press-to-talk voice capture/transcription entirely.
                            (voice.voice_enabled)

BEHAVIOUR / REGISTER:
    DR_ALEX_CRISIS_CARD_STYLE   ``full`` (default, safe fallback) | ``graded``. Also settable
                                via ``[safety] crisis_card_style``. (config.crisis_card_style)
    DR_ALEX_NOTION_DETAIL       ``summary`` (default) | ``structured`` | ``full`` — Notion
                                mirror detail dial. Also ``[notion] detail_level``.
    DR_ALEX_TEST_TRAFFIC        Truthy marks the session as synthetic/test traffic so its
                                turns are tagged and excluded from real-signal rollups.

MODEL / BINARY:
    DR_ALEX_MODEL       Override the Claude model id used for turns + recorded as
                        ``model_version`` telemetry. (llm, telemetry)
    DR_ALEX_CLAUDE_BIN  Path to the ``claude`` CLI binary (default: resolve on PATH). (llm)

PATHS / STORAGE (all default under the install root; override for tests or a vault migration):
    DR_ALEX_STATE_DB          ``state.db`` location (default ``<data>/state.db``). (statedb)
    DR_ALEX_ACTIVE_FILE       Canonical Active File path (council D4; the PraxVault migration
                              point). Also ``[records] active_file``. (config.active_file_path)
    DR_ALEX_RECORDS_DIR       0700 records dir holding the Active File. Also ``[records] dir``.
    DR_ALEX_EXPORTS_DIR       0700 dir for date-ranged exports. Also ``[exports] dir``.
    DR_ALEX_PAIRING_DB        Device-pairing token db location. (pairing)
    DR_ALEX_CHECKIN_STATE     Nightly check-in state file location. (checkin)
    DR_ALEX_AGENT_MEMORY_ROOT Root of the durable agent-memory store. (memstore)
    DR_ALEX_AUDIO_TMP         Scratch dir for transient voice audio. (voice)

See README.md / AGENTS.md for the operator-facing summary; this docstring is the authoritative
list. When you add a new ``DR_ALEX_*`` var, add it here.
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
