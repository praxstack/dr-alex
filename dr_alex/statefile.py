"""Tiny JSON session-state store under ``data/``.

Holds the small facts memory needs BETWEEN sessions:
  - ``last_session_at`` / ``last_topic``  → the G5 delta-banded re-orientation preamble;
  - ``continuity_generated_at``           → the G8 loud-staleness banner;
  - ``unfinalized``                       → the crash-safety marker for the session-end
                                            fan-out (present ⇒ a fan-out did not complete).

The unfinalized marker's derived digest is Fernet-encrypted at rest; its operational fields and
top-level timestamps/topic remain plaintext. The file is written 0600 and gitignored. Writes are
atomic (temp + ``os.replace``) so a process crash cannot leave a half-written file; ``fsync`` is
best-effort, so a machine crash can still lose the last write. ``load`` tolerates a missing or
malformed outer file by returning empty state, while an encrypted marker that cannot be decoded
fails loudly during recovery.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dr_alex import crypto, paths

_STATE_RELPATH = ("data", "session_state.json")
_ENCRYPTED_MARKER_FIELDS = frozenset(
    {
        "session_id",
        "started_at",
        "end_ts",
        "inbox_filename",
        "digest_enc",
        "remembered",
        "inbox_written",
        "continuity_written",
    }
)

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


@dataclass
class SessionState:
    last_session_at: str | None = None
    last_topic: str | None = None
    continuity_generated_at: str | None = None
    unfinalized: dict | None = None  # serialized UnfinalizedMarker, or None

    def marker(self) -> UnfinalizedMarker | None:
        if not self.unfinalized:
            return None
        raw = self.unfinalized
        if "digest_enc" in raw:
            if set(raw) != _ENCRYPTED_MARKER_FIELDS or not (
                all(
                    isinstance(raw[field], str)
                    for field in (
                        "session_id",
                        "started_at",
                        "end_ts",
                        "inbox_filename",
                        "digest_enc",
                    )
                )
                and isinstance(raw["remembered"], list)
                and all(
                    isinstance(index, int) and not isinstance(index, bool)
                    for index in raw["remembered"]
                )
                and isinstance(raw["inbox_written"], bool)
                and isinstance(raw["continuity_written"], bool)
            ):
                raise crypto.CryptoError("invalid encrypted session marker")
            try:
                decrypted = crypto.decrypt(raw["digest_enc"].encode("ascii"))
                if decrypted is None:
                    raise crypto.CryptoError("invalid encrypted session marker")
                digest = json.loads(decrypted)
            except crypto.CryptoError:
                raise
            except (TypeError, UnicodeError, ValueError) as exc:
                raise crypto.CryptoError("invalid encrypted session marker") from exc
            if not isinstance(digest, dict):
                raise crypto.CryptoError("invalid encrypted session marker")
            return UnfinalizedMarker(
                session_id=raw["session_id"],
                started_at=raw["started_at"],
                end_ts=raw["end_ts"],
                inbox_filename=raw["inbox_filename"],
                digest=digest,
                remembered=list(raw["remembered"]),
                inbox_written=raw["inbox_written"],
                continuity_written=raw["continuity_written"],
            )
        try:
            return UnfinalizedMarker(**raw)
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
        payload = json.dumps(asdict(state), ensure_ascii=False, indent=2)
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
    digest = payload.pop("digest")
    encrypted = crypto.encrypt(json.dumps(digest, sort_keys=True, separators=(",", ":")))
    if encrypted is None:
        raise crypto.CryptoError("could not encrypt session marker")
    try:
        payload["digest_enc"] = encrypted.decode("ascii")
    except (AttributeError, UnicodeError) as exc:
        raise crypto.CryptoError("could not encrypt session marker") from exc

    def _set(st: SessionState) -> None:
        current = st.unfinalized
        if current and current.get("session_id") != marker.session_id:
            raise RuntimeError("cannot replace pending marker for another session")
        st.unfinalized = payload

    update(_set, path)


def clear_unfinalized(path: Path | None = None) -> None:
    """Drop the crash-recovery marker. Atomic against concurrent writers."""

    def _clear(st: SessionState) -> None:
        st.unfinalized = None

    update(_clear, path)
