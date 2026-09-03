"""Tiny JSON session-state store under ``data/`` — the Phase-3 stand-in for Phase-4's
``state.db``.

Holds only the small facts memory needs BETWEEN sessions:
  - ``last_session_at`` / ``last_topic``  → the G5 delta-banded re-orientation preamble;
  - ``continuity_generated_at``           → the G8 loud-staleness banner;
  - ``unfinalized``                       → the crash-safety marker for the session-end
                                            fan-out (present ⇒ a fan-out did not complete).

Written 0600 and gitignored (Directive 3 — nothing clinical or derived is ever tracked).
The file itself is metadata only (timestamps + a short topic label); the topic is a
non-clinical thread name, never a transcript. Writes are atomic (temp + ``os.replace``) so a
*process* crash can never leave a half-written state file; ``fsync`` is best-effort on top, so
a *machine* crash (power cut / panic) can still lose the last write — ``load`` tolerates that
by returning empty state rather than raising.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dr_alex import crypto, paths

_STATE_RELPATH = ("data", "session_state.json")
_log = logging.getLogger(__name__)

#: Serializes every read-modify-write of the state file. The TUI runs
#: ``fanout.recover_if_needed`` on a Textual ``@work(thread=True)`` worker while the main
#: thread can enter ``finalize_session`` — two interleaved read-modify-writes would clobber
#: one crash marker. The lock only helps if the WHOLE cycle is inside it, which is why
#: ``update()`` exists and why callers must not hand-roll load/mutate/save. Re-entrant
#: because ``update`` calls ``save`` while holding it. Deliberately in-process only: a
#: cross-process lockfile would add a stale-lock hang at 3am for a case (two TUIs at once)
#: that does not occur.
_LOCK = threading.RLock()


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
    mirror_written: bool = False


@dataclass
class SessionState:
    last_session_at: str | None = None
    last_topic: str | None = None
    continuity_generated_at: str | None = None
    unfinalized: dict | None = None  # serialized UnfinalizedMarker, or None

    def marker(self) -> UnfinalizedMarker | None:
        if not self.unfinalized:
            return None
        payload = dict(self.unfinalized)
        if "digest_enc" in payload:
            token = payload.pop("digest_enc")
            try:
                if not isinstance(token, str):
                    raise TypeError("digest token must be text")
                digest = json.loads(crypto.decrypt(token.encode("ascii")) or "")
                if not isinstance(digest, dict):
                    raise TypeError("digest payload must be an object")
                payload["digest"] = digest
            except (crypto.CryptoError, UnicodeError, TypeError, ValueError) as exc:
                _log.warning("unfinalized marker decrypt failed: %s", type(exc).__name__)
                return None
        try:
            return UnfinalizedMarker(**payload)
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
    """Atomically write the state file 0600 (parent dir 0700).

    ``fsync`` on the temp and on the parent directory is BEST-EFFORT: today there is no fsync
    at all, so swallowing a flush failure is not a new silent failure, whereas letting it raise
    would add a brand-new failure point to a fan-out that has no local handling. (On Darwin
    ``os.fsync`` does not flush the drive's write cache — that needs ``F_FULLFSYNC`` — so this
    narrows the power-loss window rather than closing it.)
    """
    p = path or state_path()
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p.parent, 0o700)
        except OSError:
            pass
        serialized = asdict(state)
        marker = serialized.get("unfinalized")
        if isinstance(marker, dict) and "digest" in marker:
            digest = marker.pop("digest")
            digest_json = json.dumps(
                digest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            digest_enc = crypto.encrypt(digest_json)
            if digest_enc is None:
                raise RuntimeError("digest encryption returned no token")
            marker["digest_enc"] = digest_enc.decode("ascii")
        payload = json.dumps(serialized, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".session_state.", suffix=".tmp")
        closed = False
        try:
            os.write(fd, payload.encode("utf-8"))
            try:
                os.fsync(fd)
            except OSError:
                pass
            os.close(fd)
            closed = True
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
            try:  # make the rename itself durable
                dfd = os.open(str(p.parent), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
        except OSError:
            if not closed:  # never double-close: the fd number may have been reused
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def update(mutate: Callable[[SessionState], None], path: Path | None = None) -> SessionState:
    """Atomically read-modify-write the state file; returns the state as persisted.

    THIS IS THE ONLY CORRECT WAY TO CHANGE AN EXISTING FIELD. A caller that does its own
    ``load()`` → mutate → ``save()`` holds no lock across the gap, so a concurrent writer's
    change is silently clobbered by the stale copy — and the field most likely to be lost is
    ``unfinalized``, the crash-recovery marker. Losing it means a crashed fan-out is never
    replayed and the continuity brief stays silently stale.

    ``mutate`` runs while the lock is held, so keep it pure and fast: no I/O, no LLM calls, no
    re-entry into other ``statefile`` functions except the ones documented as re-entrant. Raising
    from ``mutate`` aborts the write and leaves the previous state intact.

    The returned state is a SNAPSHOT for reading. Mutating it does not persist anything, and
    passing it back to ``save()`` re-introduces exactly the lost-update this function exists
    to prevent — call ``update()`` again instead.
    """
    with _LOCK:
        st = load(path)
        mutate(st)
        save(st, path)
        return st


def set_unfinalized(marker: UnfinalizedMarker, path: Path | None = None) -> None:
    """Persist the crash-recovery marker. Atomic against concurrent writers."""
    payload = asdict(marker)

    def _set(st: SessionState) -> None:
        st.unfinalized = payload

    update(_set, path)


def clear_unfinalized(path: Path | None = None) -> None:
    """Drop the crash-recovery marker. Atomic against concurrent writers."""

    def _clear(st: SessionState) -> None:
        st.unfinalized = None

    update(_clear, path)
