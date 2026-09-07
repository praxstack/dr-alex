"""Tiny JSON session-state store under ``data/`` — the Phase-3 stand-in for Phase-4's
``state.db``.

Holds only the small facts memory needs BETWEEN sessions:
  - ``last_session_at`` / ``last_topic``  → the G5 delta-banded re-orientation preamble;
  - ``continuity_generated_at``           → the G8 loud-staleness banner;
  - ``unfinalized``                       → the crash-safety marker for the session-end
                                            fan-out (present ⇒ a fan-out did not complete).

Written 0600 and gitignored (Directive 3 — nothing clinical or derived is ever tracked).
The recovery digest is Fernet-encrypted before serialization, using the existing state key.
The remaining fields are metadata; the topic is a non-clinical thread name, never a
transcript. Valid legacy markers migrate on load. Unreadable markers raise body-free errors
and block writes so pending recovery is never silently discarded.
Writes are atomic (temp + ``os.replace``) so a
*process* crash can never leave a half-written state file; ``fsync`` is best-effort on top, so
a *machine* crash (power cut / panic) can still lose the last write — ``load`` tolerates that
by returning empty state rather than raising.
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
        raw = _decode_marker(self.unfinalized)
        return UnfinalizedMarker(**raw) if raw is not None else None


def _decode_marker(raw: object) -> dict | None:
    """Validate before any recovery step; never expose payloads in exception chains."""
    if raw is None:
        return None
    try:
        if not isinstance(raw, dict):
            raise ValueError
        raw = dict(raw)
        if "digest_enc" in raw:
            if "digest" in raw or not isinstance(raw["digest_enc"], str):
                raise ValueError
            token = raw.pop("digest_enc").encode("ascii")
            raw["digest"] = json.loads(crypto.decrypt(token, create=False))
        marker = UnfinalizedMarker(**raw)
        if not (
            all(
                isinstance(value, str)
                for value in (
                    marker.session_id,
                    marker.started_at,
                    marker.end_ts,
                    marker.inbox_filename,
                )
            )
            and isinstance(marker.digest, dict)
            and isinstance(marker.remembered, list)
            and all(type(index) is int and index >= 0 for index in marker.remembered)
            and isinstance(marker.inbox_written, bool)
            and isinstance(marker.continuity_written, bool)
        ):
            raise ValueError
        return asdict(marker)
    except Exception:  # noqa: BLE001 — keyring and decoder errors may include private bodies
        raise crypto.CryptoError("session recovery marker is unreadable; state preserved") from None


def _encode_marker(raw: object) -> dict | None:
    marker = _decode_marker(raw)
    if marker is None:
        return None
    try:
        digest = json.dumps(marker.pop("digest"), ensure_ascii=False)
        marker["digest_enc"] = crypto.encrypt(digest).decode("ascii")
    except Exception:  # noqa: BLE001 — never leak keyring or serialization exception bodies
        raise crypto.CryptoError("could not encrypt session recovery marker") from None
    return marker


def load(path: Path | None = None) -> SessionState:
    """Load and atomically migrate a valid legacy marker; unreadable markers fail closed.

    Malformed outer JSON retains the historical empty-state read fallback. Writers refuse
    it, because it may contain a pending marker that cannot safely be replaced.
    """
    with _LOCK:
        return _load(path or state_path())


def _read_data(p: Path, *, strict: bool = False) -> dict:
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError):
        raise crypto.CryptoError("session state is unreadable; state preserved") from None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, TypeError):
        if strict:
            raise crypto.CryptoError("session state is unreadable; state preserved") from None
        return {}
    return data


def _load(p: Path, *, strict: bool = False) -> SessionState:
    data = _read_data(p, strict=strict)
    marker = _decode_marker(data.get("unfinalized"))
    if marker is not None and "digest_enc" not in data["unfinalized"]:
        data["unfinalized"] = _encode_marker(marker)
        _write_data(data, p)
    return SessionState(
        last_session_at=data.get("last_session_at"),
        last_topic=data.get("last_topic"),
        continuity_generated_at=data.get("continuity_generated_at"),
        unfinalized=marker,
    )


def save(state: SessionState, path: Path | None = None) -> None:
    """Atomically write the state file 0600 (parent dir 0700).

    Refuse to overwrite unreadable recovery material, even for a direct save. Merge known
    fields into the existing object so migration/updates preserve unrelated state fields.
    """
    p = path or state_path()
    with _LOCK:
        data = _read_data(p, strict=True)
        _decode_marker(data.get("unfinalized"))
        data.update(asdict(state))
        data["unfinalized"] = _encode_marker(state.unfinalized)
        _write_data(data, p)


def _write_data(data: dict, p: Path) -> None:
    """Write already-encrypted serialized state, while the caller holds ``_LOCK``.

    ``fsync`` on the temp and on the parent directory is BEST-EFFORT: today there is no fsync
    at all, so swallowing a flush failure is not a new silent failure, whereas letting it raise
    would add a brand-new failure point to a fan-out that has no local handling. (On Darwin
    ``os.fsync`` does not flush the drive's write cache — that needs ``F_FULLFSYNC`` — so this
    narrows the power-loss window rather than closing it.)
    """
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p.parent, 0o700)
        except OSError:
            pass
        payload = json.dumps(data, ensure_ascii=False, indent=2)
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
        st = _load(path or state_path(), strict=True)
        mutate(st)
        save(st, path)
        return st


def set_unfinalized(marker: UnfinalizedMarker, path: Path | None = None) -> None:
    """Persist the crash-recovery marker. Atomic against concurrent writers."""
    payload = asdict(marker)

    def _set(st: SessionState) -> None:
        pending = st.marker()
        if pending is not None and pending.session_id != marker.session_id:
            raise RuntimeError("another session is already pending recovery")
        st.unfinalized = payload

    update(_set, path)


def clear_unfinalized(path: Path | None = None) -> None:
    """Drop the crash-recovery marker. Atomic against concurrent writers."""

    def _clear(st: SessionState) -> None:
        st.unfinalized = None

    update(_clear, path)
