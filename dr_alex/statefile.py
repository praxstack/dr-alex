"""Tiny JSON session-state store under ``data/`` — the Phase-3 stand-in for Phase-4's
``state.db``.

Holds only the small facts memory needs BETWEEN sessions:
  - ``last_session_at`` / ``last_topic``  → the G5 delta-banded re-orientation preamble;
  - ``continuity_generated_at``           → the G8 loud-staleness banner;
  - ``unfinalized``                       → the crash-safety marker for the session-end
                                            fan-out (present ⇒ a fan-out did not complete).

Written 0600 and gitignored (Directive 3 — nothing clinical or derived is ever tracked).
The file itself is metadata only (timestamps + a short topic label); the topic is a
non-clinical thread name, never a transcript. Writes are atomic (temp + ``os.replace``) so
a crash can never leave a half-written state file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dr_alex import paths

_STATE_RELPATH = ("data", "session_state.json")


def state_path() -> Path:
    """Absolute path to the state file (created lazily under the repo/install ``data/``)."""
    # data/ already exists in the source tree; fall back to <pkg parent>/data otherwise.
    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / _STATE_RELPATH[1]


@dataclass
class UnfinalizedMarker:
    """A session-end fan-out that began but has not been confirmed complete."""

    session_id: str
    started_at: str  # ISO8601 Z
    end_ts: str  # ISO8601 Z — the deterministic timestamp for this finalization
    inbox_filename: str  # deterministic, so a replay reuses the SAME inbox file
    digest: dict = field(default_factory=dict)  # the already-distilled digest (no re-call)
    remembered: list[int] = field(default_factory=list)  # indices of durable facts written
    inbox_written: bool = False
    continuity_written: bool = False


@dataclass
class SessionState:
    last_session_at: str | None = None
    last_topic: str | None = None
    continuity_generated_at: str | None = None
    unfinalized: dict | None = None  # serialized UnfinalizedMarker, or None

    def marker(self) -> UnfinalizedMarker | None:
        if not self.unfinalized:
            return None
        try:
            return UnfinalizedMarker(**self.unfinalized)
        except (TypeError, ValueError):
            return None


def load(path: Path | None = None) -> SessionState:
    """Load state, tolerating a missing or corrupt file (→ empty state, never a crash)."""
    p = path or state_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return SessionState()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return SessionState()
    if not isinstance(data, dict):
        return SessionState()
    return SessionState(
        last_session_at=data.get("last_session_at"),
        last_topic=data.get("last_topic"),
        continuity_generated_at=data.get("continuity_generated_at"),
        unfinalized=data.get("unfinalized") if isinstance(data.get("unfinalized"), dict) else None,
    )


def save(state: SessionState, path: Path | None = None) -> None:
    """Atomically write the state file 0600 (parent dir 0700)."""
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    payload = json.dumps(asdict(state), ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".session_state.", suffix=".tmp")
    try:
        os.write(fd, payload.encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_unfinalized(marker: UnfinalizedMarker, path: Path | None = None) -> None:
    st = load(path)
    st.unfinalized = asdict(marker)
    save(st, path)


def clear_unfinalized(path: Path | None = None) -> None:
    st = load(path)
    st.unfinalized = None
    save(st, path)
