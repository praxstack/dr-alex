"""``state.db`` — the encrypted local telemetry store (Phase 4).

A single SQLite database at ``data/state.db`` (file 0600, ``data/`` 0700, gitignored) holding
Dr. Alex's between-session telemetry: mood chips, homework, per-turn traces, session records
(for streaks + the late-night dependency monitor), encrypted transcripts (for the nightly
eval), the G10 repair-ack flag, and eval scores.

**Council D2 — plaintext is an ALLOWLIST.** Only ints/floats (mood 1–10, scores), enums
(``phase``, ``status``, ``tier``, ``kind``), timestamps, ULIDs/ids, booleans, and counts sit
in the clear. Every free-text value — transcript bodies, homework titles, note bodies — is
Fernet-encrypted by :mod:`dr_alex.crypto` *before* it reaches SQLite, so no plaintext therapy
content is present in the db file (or its journal) at rest. ``model_version`` and
``prompt_hash`` are telemetry identifiers/hashes, not free text, and stay plaintext (G9).

Every operation degrades to a safe no-op / empty result rather than raising, so telemetry can
never break a session. A kill-switch (``DR_ALEX_TELEMETRY_OFF``) disables the store entirely.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from dr_alex import crypto, timeutil, ulid
from dr_alex.timeutil import IST  # re-exported: exporters import IST from statedb (D13)

_log = logging.getLogger("dr_alex.statedb")

_STATE_DB_ENV = "DR_ALEX_STATE_DB"
_TELEMETRY_OFF_ENV = "DR_ALEX_TELEMETRY_OFF"

MOOD_PHASES = ("open", "close")
HOMEWORK_STATUSES = ("open", "done", "dropped")

# G18 default clustering thresholds (late-night sessions → gentle surface).
NIGHT_HOURS_IST = set(range(0, 5))  # 00:00–04:59 IST
LATE_NIGHT_WINDOW_DAYS = 7
LATE_NIGHT_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Location + enablement
# ---------------------------------------------------------------------------


def telemetry_enabled() -> bool:
    """False when the kill-switch is set — the store then behaves as a no-op."""
    return os.environ.get(_TELEMETRY_OFF_ENV, "").strip().lower() not in ("1", "true", "yes", "on")


def state_db_path() -> Path:
    """Absolute path to ``state.db`` (env-overridable so tests use a throwaway file)."""
    override = os.environ.get(_STATE_DB_ENV)
    if override:
        return Path(override)
    from dr_alex import paths

    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / "state.db"


def _now_iso(now: _dt.datetime | None = None) -> str:
    return timeutil.now_iso(now)


def _ist(now: _dt.datetime | None = None) -> _dt.datetime:
    return timeutil.to_ist(now)


# ---------------------------------------------------------------------------
# Schema + connection
# ---------------------------------------------------------------------------

#: Bump when ``_SCHEMA`` changes so an existing db re-applies it once (D17). PRAGMA
#: user_version is stored in the db file, so the schema is applied once per file, not per op.
_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY,
    started_ts        TEXT NOT NULL,
    ended_ts          TEXT,
    started_date_ist  TEXT NOT NULL,
    started_hour_ist  INTEGER NOT NULL,
    is_test_traffic   INTEGER NOT NULL DEFAULT 0,
    safety_probe_asked INTEGER NOT NULL DEFAULT 0,
    safety_probe_declined INTEGER NOT NULL DEFAULT 0,
    recent_risk       TEXT
);
CREATE TABLE IF NOT EXISTS mood_events (
    id          TEXT PRIMARY KEY,
    session_id  TEXT,
    ts          TEXT NOT NULL,
    phase       TEXT NOT NULL,
    mood        INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS homework (
    id             TEXT PRIMARY KEY,
    title_enc      BLOB NOT NULL,
    assigned_date  TEXT NOT NULL,
    due            TEXT,
    source_session TEXT,
    status         TEXT NOT NULL DEFAULT 'open',
    created_ts     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turn_traces (
    id                TEXT PRIMARY KEY,
    session_id        TEXT,
    ts                TEXT NOT NULL,
    tier              TEXT NOT NULL,
    model_version     TEXT,
    prompt_hash       TEXT,
    is_test_traffic   INTEGER NOT NULL DEFAULT 0,
    safety_action     TEXT,
    dependency_action TEXT,
    register_action   TEXT
);
CREATE TABLE IF NOT EXISTS transcripts (
    id               TEXT PRIMARY KEY,
    session_id       TEXT,
    ts               TEXT NOT NULL,
    role             TEXT NOT NULL,
    body_enc         BLOB NOT NULL,
    tier             TEXT,
    is_test_traffic  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS api_events (
    id               TEXT PRIMARY KEY,
    request_id       TEXT NOT NULL,
    session_id       TEXT,
    ts               TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    payload_hash     TEXT NOT NULL,
    body_enc         BLOB NOT NULL,
    is_test_traffic  INTEGER NOT NULL DEFAULT 0,
    consumed         INTEGER NOT NULL DEFAULT 0,
    consumed_by      TEXT
);
CREATE TABLE IF NOT EXISTS turn_requests (
    request_id       TEXT PRIMARY KEY,
    session_id       TEXT,
    payload_hash     TEXT NOT NULL,
    input_enc        BLOB NOT NULL,
    created_ts       TEXT NOT NULL,
    completed_ts     TEXT,
    status           TEXT NOT NULL,
    tier             TEXT,
    response_enc     BLOB,
    response_tier    TEXT,
    safety_action    TEXT,
    is_test_traffic  INTEGER NOT NULL DEFAULT 0,
    safety_probe_asked INTEGER NOT NULL DEFAULT 0,
    safety_probe_declined INTEGER NOT NULL DEFAULT 0,
    recent_risk      TEXT
);
CREATE TABLE IF NOT EXISTS repair_acks (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    session_id  TEXT,
    acked       INTEGER NOT NULL DEFAULT 0,
    acked_ts    TEXT
);
CREATE TABLE IF NOT EXISTS eval_scores (
    id           TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    session_id   TEXT,
    score        REAL NOT NULL,
    z            REAL,
    judge_model  TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    session_id  TEXT,
    kind        TEXT NOT NULL,
    body_enc    BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS notion_pages (
    session_id  TEXT NOT NULL,
    db_kind     TEXT NOT NULL,
    page_id     TEXT NOT NULL,
    updated_ts  TEXT NOT NULL,
    PRIMARY KEY (session_id, db_kind)
);
"""


def _prepare_paths(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass


@contextmanager
def _connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the db (creating + locking down perms + schema on first use)."""
    p = path or state_db_path()
    _prepare_paths(p)
    existed = p.exists()
    conn = sqlite3.connect(str(p))
    if not existed:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    try:
        # Apply the schema only when this db file hasn't been initialized to the
        # current version yet — gated by PRAGMA user_version (D17). Routine reads/writes then
        # skip the CREATE-TABLE script entirely instead of re-running it on every _connect.
        if conn.execute("PRAGMA user_version").fetchone()[0] < _SCHEMA_VERSION:
            conn.executescript(_SCHEMA)
            # v1 databases already have the original sessions table. SQLite has no
            # conditional ALTER, so tolerate duplicate-column errors while upgrading.
            for column, definition in (
                ("safety_probe_asked", "INTEGER NOT NULL DEFAULT 0"),
                ("safety_probe_declined", "INTEGER NOT NULL DEFAULT 0"),
                ("recent_risk", "TEXT"),
            ):
                try:
                    conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            for column, definition in (
                ("consumed", "INTEGER NOT NULL DEFAULT 0"),
                ("consumed_by", "TEXT"),
            ):
                try:
                    conn.execute(f"ALTER TABLE api_events ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            for column, definition in (
                ("safety_probe_asked", "INTEGER NOT NULL DEFAULT 0"),
                ("safety_probe_declined", "INTEGER NOT NULL DEFAULT 0"),
                ("recent_risk", "TEXT"),
            ):
                try:
                    conn.execute(f"ALTER TABLE turn_requests ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    """Idempotently create the db + schema (perms enforced)."""
    with _connect(path):
        pass


def healthy(path: Path | None = None) -> bool:
    """Read-only liveness probe for ``/healthz``. Never creates, migrates, or writes.

    True when the store is usable OR has simply not been created yet (it is created lazily on
    first real use, so "absent" is not "broken"). False only when the file exists and cannot
    be opened/read — i.e. corrupt, unreadable, or on a dead volume.
    """
    if not telemetry_enabled():
        return True  # kill-switch on: the store is a deliberate no-op, not a fault
    p = path or state_db_path()
    if not p.exists():
        return True
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=1.0)
        try:
            conn.execute("PRAGMA user_version").fetchone()
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001 — a health probe must never raise
        _log.warning("statedb health probe failed")
        return False


def _bool(v: object) -> int:
    return 1 if v else 0


# ---------------------------------------------------------------------------
# Sessions (drive streaks + the late-night dependency monitor)
# ---------------------------------------------------------------------------


def start_session(
    session_id: str,
    *,
    now: _dt.datetime | None = None,
    is_test_traffic: bool = False,
    path: Path | None = None,
) -> bool:
    if not telemetry_enabled():
        return False
    ist = _ist(now)
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions "
                "(id, started_ts, ended_ts, started_date_ist, started_hour_ist, is_test_traffic) "
                "VALUES (?,?,?,?,?,?)",
                (
                    session_id,
                    _now_iso(now),
                    None,
                    ist.strftime("%Y-%m-%d"),
                    ist.hour,
                    _bool(is_test_traffic),
                ),
            )
    except sqlite3.Error as exc:
        _log.warning("start_session failed: %s", type(exc).__name__)
        return False
    return True


@dataclass
class PersistedSessionState:
    safety_probe_asked: bool = False
    safety_probe_declined: bool = False
    recent_risk: str | None = None


def load_session_state(session_id: str, *, path: Path | None = None) -> PersistedSessionState:
    """Load the small safety state needed to resume a Room session."""
    if not telemetry_enabled():
        return PersistedSessionState()
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT safety_probe_asked, safety_probe_declined, recent_risk "
                "FROM sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            # Completion stores the same resume flags on the request row.  Use the latest
            # completed turn as a deterministic fallback if an older process died between
            # its reply commit and the separate session-state write.
            completed = conn.execute(
                "SELECT safety_probe_asked, safety_probe_declined, recent_risk "
                "FROM turn_requests WHERE session_id=? AND status='completed' "
                "ORDER BY completed_ts DESC LIMIT 1",
                (session_id,),
            ).fetchone()
    except sqlite3.Error:
        return PersistedSessionState()
    if row is None and completed is None:
        return PersistedSessionState()
    if row is None:
        row = (0, 0, None)
    if completed is not None:
        return PersistedSessionState(
            bool(row[0]) or bool(completed[0]),
            bool(row[1]) or bool(completed[1]),
            completed[2] or row[2],
        )
    return PersistedSessionState(bool(row[0]), bool(row[1]), row[2])


def update_session_state(
    session_id: str,
    *,
    safety_probe_asked: bool,
    safety_probe_declined: bool,
    recent_risk: str | None,
    path: Path | None = None,
) -> bool:
    """Persist resume-critical safety flags; return False when storage is unavailable."""
    if not telemetry_enabled():
        return False
    try:
        with _connect(path) as conn:
            cur = conn.execute(
                "UPDATE sessions SET safety_probe_asked=?, safety_probe_declined=?, "
                "recent_risk=? WHERE id=?",
                (_bool(safety_probe_asked), _bool(safety_probe_declined), recent_risk, session_id),
            )
            return cur.rowcount > 0
    except sqlite3.Error as exc:
        _log.warning("update_session_state failed: %s", type(exc).__name__)
        return False


def end_session(
    session_id: str, *, now: _dt.datetime | None = None, path: Path | None = None
) -> bool:
    if not telemetry_enabled():
        return False
    try:
        with _connect(path) as conn:
            conn.execute("UPDATE sessions SET ended_ts=? WHERE id=?", (_now_iso(now), session_id))
    except sqlite3.Error as exc:
        _log.warning("end_session failed: %s", type(exc).__name__)
        return False
    return True


def checkin_dates(*, path: Path | None = None) -> list[str]:
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT started_date_ist FROM sessions ORDER BY started_date_ist"
            ).fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Mood chips (item 3) — plaintext ints/enums; feed the Phase-3 digest seam.
# ---------------------------------------------------------------------------


def record_mood(
    phase: str,
    mood: int,
    *,
    session_id: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> str | None:
    """Record a mood chip (1–10) at ``phase`` ('open'|'close'). Returns the row id or None."""
    if not telemetry_enabled():
        return None
    if phase not in MOOD_PHASES:
        raise ValueError(f"phase must be one of {MOOD_PHASES}, got {phase!r}")
    try:
        m = int(mood)
    except (ValueError, TypeError):
        return None
    if not 1 <= m <= 10:
        raise ValueError("mood must be an integer 1–10")
    rid = ulid.new()
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO mood_events (id, session_id, ts, phase, mood) VALUES (?,?,?,?,?)",
                (rid, session_id, _now_iso(now), phase, m),
            )
    except sqlite3.Error as exc:
        _log.warning("record_mood failed: %s", type(exc).__name__)
        return None
    return rid


@dataclass
class MoodStats:
    points: int = 0
    latest: int | None = None
    mean: float | None = None
    delta: float | None = None  # last minus first over the window
    window_days: int = 30


def _mood_rows(days: int, now: _dt.datetime | None, path: Path | None) -> list[tuple[str, int]]:
    cutoff = _now_iso((now or _dt.datetime.now(_dt.UTC)) - _dt.timedelta(days=days))
    try:
        with _connect(path) as conn:
            return conn.execute(
                "SELECT ts, mood FROM mood_events WHERE ts >= ? ORDER BY ts", (cutoff,)
            ).fetchall()
    except sqlite3.Error:
        return []


def mood_stats(
    *, days: int = 30, now: _dt.datetime | None = None, path: Path | None = None
) -> MoodStats:
    if not telemetry_enabled():
        return MoodStats(window_days=days)
    rows = _mood_rows(days, now, path)
    if not rows:
        return MoodStats(window_days=days)
    moods = [m for _, m in rows]
    delta = float(moods[-1] - moods[0]) if len(moods) >= 2 else 0.0
    return MoodStats(
        points=len(moods),
        latest=moods[-1],
        mean=round(sum(moods) / len(moods), 2),
        delta=delta,
        window_days=days,
    )


def daily_mood(
    *, days: int = 30, now: _dt.datetime | None = None, path: Path | None = None
) -> list[float | None]:
    """Latest mood per IST-day over the last ``days`` days (oldest→newest) for the sparkline.

    Days without a mood chip render as ``None`` (a gap, not a fabricated value).
    """
    if not telemetry_enabled():
        return [None] * days
    rows = _mood_rows(days, now, path)
    by_day: dict[str, int] = {}
    for ts, mood in rows:  # rows are ordered by ts, so the last write per day wins
        dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
        by_day[dt.strftime("%Y-%m-%d")] = mood
    today_ist = _ist(now).date()
    out: list[float | None] = []
    for i in range(days - 1, -1, -1):
        key = (today_ist - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
        out.append(float(by_day[key]) if key in by_day else None)
    return out


def session_moods(session_id: str, *, path: Path | None = None) -> tuple[int | None, int | None]:
    """Return (open_mood, close_mood) for a session — the latest chip of each phase, or None.

    This is the seam that lets the Phase-3 session digest use the user's *reported* mood
    (ground truth) for ``mood_in``/``mood_out`` instead of the model's inference.
    """
    if not telemetry_enabled():
        return (None, None)
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT phase, mood FROM mood_events WHERE session_id=? ORDER BY ts",
                (session_id,),
            ).fetchall()
    except sqlite3.Error:
        return (None, None)
    open_mood = close_mood = None
    for phase, mood in rows:  # ordered by ts, so the last of each phase wins
        if phase == "open":
            open_mood = mood
        elif phase == "close":
            close_mood = mood
    return (open_mood, close_mood)


def risk_tier_max(
    *, days: int = 30, now: _dt.datetime | None = None, path: Path | None = None
) -> str | None:
    if not telemetry_enabled():
        return None
    cutoff = _now_iso((now or _dt.datetime.now(_dt.UTC)) - _dt.timedelta(days=days))
    rank = {"GREEN": 0, "AMBER": 1, "RED": 2}
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT tier FROM turn_traces WHERE ts >= ?", (cutoff,)
            ).fetchall()
    except sqlite3.Error:
        return None
    tiers = [r[0] for r in rows if r[0] in rank]
    return max(tiers, key=lambda t: rank[t]) if tiers else None


# ---------------------------------------------------------------------------
# Homework (item 4) — title Fernet-encrypted.
# ---------------------------------------------------------------------------


@dataclass
class Homework:
    id: str
    title: str
    assigned_date: str
    due: str | None
    source_session: str | None
    status: str
    created_ts: str


def add_homework(
    title: str,
    *,
    assigned_date: str | None = None,
    due: str | None = None,
    source_session: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> str | None:
    if not telemetry_enabled():
        return None
    if not title or not title.strip():
        return None
    rid = ulid.new()
    assigned = assigned_date or _ist(now).strftime("%Y-%m-%d")
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO homework (id, title_enc, assigned_date, due, source_session, status, created_ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    rid,
                    crypto.encrypt(title.strip()),
                    assigned,
                    due,
                    source_session,
                    "open",
                    _now_iso(now),
                ),
            )
    except sqlite3.Error as exc:
        _log.warning("add_homework failed: %s", type(exc).__name__)
        return None
    return rid


def _rows_to_homework(rows) -> list[Homework]:
    out: list[Homework] = []
    for r in rows:
        try:
            title = crypto.decrypt(r[1]) or ""
        except crypto.CryptoError:
            title = "(unreadable — key mismatch)"
        out.append(
            Homework(
                id=r[0],
                title=title,
                assigned_date=r[2],
                due=r[3],
                source_session=r[4],
                status=r[5],
                created_ts=r[6],
            )
        )
    return out


def open_homework(*, path: Path | None = None) -> list[Homework]:
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT id, title_enc, assigned_date, due, source_session, status, created_ts "
                "FROM homework WHERE status='open' ORDER BY created_ts"
            ).fetchall()
    except sqlite3.Error:
        return []
    return _rows_to_homework(rows)


def all_homework(*, path: Path | None = None) -> list[Homework]:
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT id, title_enc, assigned_date, due, source_session, status, created_ts "
                "FROM homework ORDER BY created_ts"
            ).fetchall()
    except sqlite3.Error:
        return []
    return _rows_to_homework(rows)


def set_homework_status(hw_id: str, status: str, *, path: Path | None = None) -> bool:
    if not telemetry_enabled():
        return False
    if status not in HOMEWORK_STATUSES:
        raise ValueError(f"status must be one of {HOMEWORK_STATUSES}")
    try:
        with _connect(path) as conn:
            cur = conn.execute("UPDATE homework SET status=? WHERE id=?", (status, hw_id))
            return cur.rowcount > 0
    except sqlite3.Error as exc:
        _log.warning("set_homework_status failed: %s", type(exc).__name__)
        return False


def mark_homework_done(hw_id: str, *, path: Path | None = None) -> bool:
    return set_homework_status(hw_id, "done", path=path)


# ---------------------------------------------------------------------------
# G9 — per-turn trace with model_version + prompt_hash + is_test_traffic.
# ---------------------------------------------------------------------------


def record_turn_trace(
    *,
    session_id: str | None,
    tier: str,
    model_version: str | None,
    prompt_hash: str | None,
    is_test_traffic: bool,
    safety_action: str = "none",
    dependency_action: str = "clean",
    register_action: str = "clean",
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> str | None:
    if not telemetry_enabled():
        return None
    rid = ulid.new()
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO turn_traces (id, session_id, ts, tier, model_version, prompt_hash, "
                "is_test_traffic, safety_action, dependency_action, register_action) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    session_id,
                    _now_iso(now),
                    tier,
                    model_version,
                    prompt_hash,
                    _bool(is_test_traffic),
                    safety_action,
                    dependency_action,
                    register_action,
                ),
            )
    except sqlite3.Error as exc:
        _log.warning("record_turn_trace failed: %s", type(exc).__name__)
        return None
    return rid


# ---------------------------------------------------------------------------
# API input + idempotent completed turns.
# ---------------------------------------------------------------------------


class RequestPayloadConflict(ValueError):
    """A request id was reused for a different payload."""


@dataclass
class TurnRequest:
    request_id: str
    session_id: str | None
    payload_hash: str
    status: str
    response: str | None = None
    tier: str | None = None
    safety_action: str | None = None
    # The assembled, encrypted input is distinct from payload_hash.  A retry may
    # carry only the final fragment while the pending row still owns earlier input.
    input_text: str | None = None
    safety_probe_asked: bool = False
    safety_probe_declined: bool = False
    recent_risk: str | None = None


def payload_hash(payload: object) -> str:
    """Stable body hash for request-id conflict detection (the body itself stays encrypted)."""
    import json

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _request_from_row(row) -> TurnRequest:
    input_text = None
    if row[3] is not None:
        try:
            input_text = crypto.decrypt(row[3]) or ""
        except crypto.CryptoError:
            input_text = None
    response = None
    if row[8] is not None:
        try:
            response = crypto.decrypt(row[8]) or ""
        except crypto.CryptoError:
            response = None
    return TurnRequest(
        request_id=row[0],
        session_id=row[1],
        payload_hash=row[2],
        status=row[6],
        response=response,
        tier=row[7],
        safety_action=row[9],
        input_text=input_text,
        safety_probe_asked=bool(row[11]),
        safety_probe_declined=bool(row[12]),
        recent_risk=row[13],
    )


def begin_turn_request(
    request_id: str,
    *,
    session_id: str | None,
    body: str,
    request_payload_hash: str | None = None,
    tier: str | None = None,
    event_type: str = "turn",
    fragment_request_ids: list[str] | None = None,
    path: Path | None = None,
) -> TurnRequest | None:
    """Durably accept one API request before model work.

    Existing completed rows are returned for replay; a mismatched payload is rejected. A
    ``None`` result means storage failed, so callers must not claim a durable acknowledgement.
    """
    if not telemetry_enabled() or not request_id:
        return None
    digest = request_payload_hash or payload_hash(body)
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT request_id, session_id, payload_hash, input_enc, created_ts, completed_ts, "
                "status, tier, response_enc, safety_action, is_test_traffic, "
                "safety_probe_asked, safety_probe_declined, recent_risk "
                "FROM turn_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is not None:
                if row[2] != digest or row[1] != session_id:
                    raise RequestPayloadConflict(
                        f"request id {request_id!r} reused with a different payload"
                    )
                return _request_from_row(row)
            now = _now_iso()
            test_traffic = os.environ.get("DR_ALEX_TEST_TRAFFIC") == "1"
            conn.execute(
                "INSERT INTO turn_requests "
                "(request_id, session_id, payload_hash, input_enc, created_ts, status, tier, "
                "response_enc, response_tier, safety_action, is_test_traffic) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    session_id,
                    digest,
                    crypto.encrypt(body),
                    now,
                    "pending",
                    tier,
                    None,
                    tier,
                    None,
                    _bool(test_traffic),
                ),
            )
            if (
                conn.execute(
                    "SELECT 1 FROM api_events WHERE request_id=? LIMIT 1", (request_id,)
                ).fetchone()
                is None
            ):
                conn.execute(
                    "INSERT INTO api_events (id, request_id, session_id, ts, event_type, payload_hash, "
                    "body_enc, is_test_traffic) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        ulid.new(),
                        request_id,
                        session_id,
                        now,
                        event_type,
                        digest,
                        crypto.encrypt(body),
                        _bool(test_traffic),
                    ),
                )
            # Claim only the fragment events that the caller actually coalesced. Events
            # accepted after coalescing belong to a later turn and must remain recoverable.
            ids = list(dict.fromkeys(fragment_request_ids or []))
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(
                    "UPDATE api_events SET consumed_by=? WHERE session_id=? AND event_type='fragment' "
                    f"AND request_id IN ({marks}) AND consumed=0 AND consumed_by IS NULL",
                    (request_id, session_id, *ids),
                )
            return TurnRequest(
                request_id, session_id, digest, "pending", tier=tier, input_text=body
            )
    except RequestPayloadConflict:
        raise
    except Exception as exc:  # noqa: BLE001
        _log.warning("begin_turn_request failed: %s", type(exc).__name__)
        return None


def record_api_event(
    request_id: str,
    *,
    session_id: str | None,
    body: str,
    request_payload_hash: str | None = None,
    event_type: str = "fragment",
    path: Path | None = None,
) -> str:
    """Record one raw API event, deduplicating exact retries and rejecting conflicts."""
    if not telemetry_enabled() or not request_id:
        return "disabled"
    digest = request_payload_hash or payload_hash(body)
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT payload_hash, session_id FROM api_events WHERE request_id=? ORDER BY ts LIMIT 1",
                (request_id,),
            ).fetchone()
            if row is not None:
                if row[0] != digest or row[1] != session_id:
                    raise RequestPayloadConflict(
                        f"request id {request_id!r} reused with a different payload"
                    )
                return "duplicate"
            now = _now_iso()
            conn.execute(
                "INSERT INTO api_events (id, request_id, session_id, ts, event_type, payload_hash, "
                "body_enc, is_test_traffic) VALUES (?,?,?,?,?,?,?,?)",
                (
                    ulid.new(),
                    request_id,
                    session_id,
                    now,
                    event_type,
                    digest,
                    crypto.encrypt(body),
                    _bool(os.environ.get("DR_ALEX_TEST_TRAFFIC") == "1"),
                ),
            )
            return "recorded"
    except RequestPayloadConflict:
        raise
    except Exception as exc:  # noqa: BLE001
        _log.warning("record_api_event failed: %s", type(exc).__name__)
        return "failed"


def load_unconsumed_api_events(session_id: str, *, path: Path | None = None) -> list[str]:
    """Return encrypted raw fragments not yet committed to a completed turn.

    This is deliberately limited to fragment events.  Final turn bodies are represented by
    ``turn_requests.input_enc`` and must not be replayed as an additional fragment.
    """
    if not telemetry_enabled() or not session_id:
        return []
    return [body for _request_id, body in load_unconsumed_api_event_records(session_id, path=path)]


def load_unconsumed_api_event_records(
    session_id: str, *, path: Path | None = None
) -> list[tuple[str, str]]:
    """Return ``(request_id, body)`` for recoverable raw fragment events."""
    if not telemetry_enabled() or not session_id:
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT request_id, body_enc FROM api_events WHERE session_id=? "
                "AND event_type='fragment' AND consumed=0 AND consumed_by IS NULL ORDER BY rowid",
                (session_id,),
            ).fetchall()
    except Exception:  # noqa: BLE001 — restore must remain usable if storage is unavailable
        return []
    out: list[tuple[str, str]] = []
    for request_id, body_enc in rows:
        try:
            body = crypto.decrypt(body_enc)
        except crypto.CryptoError:
            continue
        if body:
            out.append((request_id, body))
    return out


def complete_turn_request(
    request_id: str,
    *,
    user_body: str,
    reply_body: str,
    tier: str,
    safety_action: str = "none",
    safety_probe_asked: bool = False,
    safety_probe_declined: bool = False,
    recent_risk: str | None = None,
    path: Path | None = None,
) -> bool:
    """Atomically mark a request complete and append its transcript pair."""
    if not telemetry_enabled() or not request_id:
        return False
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT session_id, status FROM turn_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                return False
            if row[1] == "completed":
                return True
            sid = row[0]
            now = _now_iso()
            test_traffic = os.environ.get("DR_ALEX_TEST_TRAFFIC") == "1"
            for role, body in (("user", user_body), ("assistant", reply_body)):
                if body:
                    conn.execute(
                        "INSERT INTO transcripts (id, session_id, ts, role, body_enc, tier, "
                        "is_test_traffic) VALUES (?,?,?,?,?,?,?)",
                        (
                            ulid.new(),
                            sid,
                            now,
                            role,
                            crypto.encrypt(body),
                            tier,
                            _bool(test_traffic),
                        ),
                    )
            conn.execute(
                "UPDATE turn_requests SET completed_ts=?, status='completed', tier=?, "
                "response_enc=?, response_tier=?, safety_action=?, safety_probe_asked=?, "
                "safety_probe_declined=?, recent_risk=? WHERE request_id=?",
                (
                    now,
                    tier,
                    crypto.encrypt(reply_body),
                    tier,
                    safety_action,
                    _bool(safety_probe_asked),
                    _bool(safety_probe_declined),
                    recent_risk,
                    request_id,
                ),
            )
            # Safety resume flags and the completed reply share this transaction.  A
            # fragment assigned to this request is consumed only after that commit point.
            if sid:
                conn.execute(
                    "UPDATE sessions SET safety_probe_asked=?, safety_probe_declined=?, "
                    "recent_risk=? WHERE id=?",
                    (
                        _bool(safety_probe_asked),
                        _bool(safety_probe_declined),
                        recent_risk,
                        sid,
                    ),
                )
            conn.execute(
                "UPDATE api_events SET consumed=1 WHERE consumed_by=? AND consumed=0",
                (request_id,),
            )
            return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("complete_turn_request failed: %s", type(exc).__name__)
        return False


# ---------------------------------------------------------------------------
# Transcripts (encrypted bodies; consumed by the G13 nightly eval only).
# ---------------------------------------------------------------------------


def record_transcript(
    *,
    session_id: str | None,
    role: str,
    body: str,
    tier: str | None = None,
    is_test_traffic: bool = False,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> str | None:
    if not telemetry_enabled():
        return None
    if not body:
        return None
    rid = ulid.new()
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO transcripts (id, session_id, ts, role, body_enc, tier, is_test_traffic) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    rid,
                    session_id,
                    _now_iso(now),
                    role,
                    crypto.encrypt(body),
                    tier,
                    _bool(is_test_traffic),
                ),
            )
    except sqlite3.Error as exc:
        _log.warning("record_transcript failed: %s", type(exc).__name__)
        return None
    return rid


@dataclass
class TranscriptTurn:
    session_id: str | None
    ts: str
    role: str
    body: str
    tier: str | None
    is_test_traffic: bool


def session_ids_with_transcripts(
    *, include_test: bool = False, path: Path | None = None
) -> list[str]:
    if not telemetry_enabled():
        return []
    q = "SELECT DISTINCT session_id FROM transcripts"
    if not include_test:
        q += " WHERE is_test_traffic=0"
    q += " ORDER BY session_id"
    try:
        with _connect(path) as conn:
            return [r[0] for r in conn.execute(q).fetchall() if r[0]]
    except sqlite3.Error:
        return []


def load_transcript(session_id: str, *, path: Path | None = None) -> list[TranscriptTurn]:
    """Decrypt a session's transcript IN MEMORY (G13/R3: bodies never leave this process)."""
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT session_id, ts, role, body_enc, tier, is_test_traffic FROM transcripts "
                "WHERE session_id=? ORDER BY ts",
                (session_id,),
            ).fetchall()
    except sqlite3.Error:
        return []
    out: list[TranscriptTurn] = []
    for r in rows:
        try:
            body = crypto.decrypt(r[3]) or ""
        except crypto.CryptoError:
            continue
        out.append(
            TranscriptTurn(
                session_id=r[0],
                ts=r[1],
                role=r[2],
                body=body,
                tier=r[4],
                is_test_traffic=bool(r[5]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# G10 — one-time repair-ack after a visible malfunction.
# ---------------------------------------------------------------------------

# Malfunction kinds we acknowledge (enums, never free text).
MALFUNCTION_KINDS = ("empty_reply", "wrong_crisis_card", "llm_error")


def flag_malfunction(
    kind: str,
    *,
    session_id: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> str | None:
    """Record a visible malfunction so ONE brief ack is queued for the next session start."""
    if not telemetry_enabled():
        return None
    if kind not in MALFUNCTION_KINDS:
        kind = "llm_error"
    rid = ulid.new()
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO repair_acks (id, ts, kind, session_id, acked, acked_ts) "
                "VALUES (?,?,?,?,0,NULL)",
                (rid, _now_iso(now), kind, session_id),
            )
    except sqlite3.Error as exc:
        _log.warning("flag_malfunction failed: %s", type(exc).__name__)
        return None
    return rid


@dataclass
class RepairAck:
    id: str
    kind: str
    ts: str


def pending_repair_ack(*, path: Path | None = None) -> RepairAck | None:
    """The single oldest un-acked malfunction, or None. Fires exactly once (see mark)."""
    if not telemetry_enabled():
        return None
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT id, kind, ts FROM repair_acks WHERE acked=0 ORDER BY ts LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return None
    return RepairAck(id=row[0], kind=row[1], ts=row[2]) if row else None


def mark_repair_acked(
    ack_id: str, *, now: _dt.datetime | None = None, path: Path | None = None
) -> None:
    """Mark an ack fired AND retire any other outstanding acks (ack once, never a backlog)."""
    if not telemetry_enabled():
        return
    try:
        with _connect(path) as conn:
            conn.execute(
                "UPDATE repair_acks SET acked=1, acked_ts=? WHERE acked=0", (_now_iso(now),)
            )
    except sqlite3.Error as exc:
        _log.warning("mark_repair_acked failed: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# G18 — late-night session clustering (dependency monitor).
# ---------------------------------------------------------------------------


@dataclass
class DependencySignal:
    late_night_count: int = 0
    window_days: int = LATE_NIGHT_WINDOW_DAYS
    threshold: int = LATE_NIGHT_THRESHOLD
    flagged: bool = False


def late_night_signal(
    *,
    now: _dt.datetime | None = None,
    window_days: int = LATE_NIGHT_WINDOW_DAYS,
    threshold: int = LATE_NIGHT_THRESHOLD,
    path: Path | None = None,
) -> DependencySignal:
    """Count sessions started 00:00–04:59 IST over the trailing window (G18)."""
    if not telemetry_enabled():
        return DependencySignal(window_days=window_days, threshold=threshold)
    cutoff = _now_iso((now or _dt.datetime.now(_dt.UTC)) - _dt.timedelta(days=window_days))
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT started_hour_ist FROM sessions WHERE started_ts >= ?", (cutoff,)
            ).fetchall()
    except sqlite3.Error:
        return DependencySignal(window_days=window_days, threshold=threshold)
    count = sum(1 for (h,) in rows if h in NIGHT_HOURS_IST)
    return DependencySignal(
        late_night_count=count,
        window_days=window_days,
        threshold=threshold,
        flagged=count >= threshold,
    )


# ---------------------------------------------------------------------------
# G13 — eval scores (ONLY scores are persisted; never transcript content).
# ---------------------------------------------------------------------------


def record_eval_score(
    score: float,
    *,
    session_id: str | None = None,
    z: float | None = None,
    judge_model: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> str | None:
    if not telemetry_enabled():
        return None
    rid = ulid.new()
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO eval_scores (id, ts, session_id, score, z, judge_model) VALUES (?,?,?,?,?,?)",
                (rid, _now_iso(now), session_id, float(score), z, judge_model),
            )
    except sqlite3.Error as exc:
        _log.warning("record_eval_score failed: %s", type(exc).__name__)
        return None
    return rid


def recent_eval_scores(*, limit: int = 30, path: Path | None = None) -> list[float]:
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT score FROM eval_scores ORDER BY ts DESC LIMIT ?", (int(limit),)
            ).fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in reversed(rows)]


def last_eval_at(*, path: Path | None = None) -> str | None:
    if not telemetry_enabled():
        return None
    try:
        with _connect(path) as conn:
            row = conn.execute("SELECT ts FROM eval_scores ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Phase 6 — Notion page idempotency map (session_id + db_kind → page_id).
#
# The stable ULID session_id is the idempotency key: the mirror stores the page_id Notion
# returns so a re-run PATCHes the SAME page instead of creating a duplicate. Page ids are
# opaque Notion identifiers (not free text / not clinical content) so they sit in the clear.
# ---------------------------------------------------------------------------

NOTION_DB_KINDS = ("sessions", "homework")


def get_notion_page_id(session_id: str, db_kind: str, *, path: Path | None = None) -> str | None:
    if not telemetry_enabled():
        return None
    try:
        with _connect(path) as conn:
            row = conn.execute(
                "SELECT page_id FROM notion_pages WHERE session_id=? AND db_kind=?",
                (session_id, db_kind),
            ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def set_notion_page_id(
    session_id: str,
    db_kind: str,
    page_id: str,
    *,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> None:
    if not telemetry_enabled():
        return
    try:
        with _connect(path) as conn:
            conn.execute(
                "INSERT INTO notion_pages (session_id, db_kind, page_id, updated_ts) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(session_id, db_kind) DO UPDATE SET page_id=excluded.page_id, "
                "updated_ts=excluded.updated_ts",
                (session_id, db_kind, page_id, _now_iso(now)),
            )
    except sqlite3.Error as exc:
        _log.warning("set_notion_page_id failed: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# Phase 6 — window snapshot (the G11 Shreya-prep packet reads ONLY this).
#
# Everything here is derived from the ALREADY-STORED telemetry; the pattern corpus is
# decrypted IN MEMORY (R3: bodies never leave this process) and used only for deterministic
# named-pattern matching inside the local packet.
# ---------------------------------------------------------------------------


@dataclass
class WindowSession:
    id: str
    started_ts: str
    date_ist: str
    hour_ist: int
    is_test_traffic: bool
    open_mood: int | None = None
    close_mood: int | None = None


@dataclass
class WindowSnapshot:
    from_ts: str
    to_ts: str
    window_days: int
    sessions: list[WindowSession] = field(default_factory=list)
    homework: list[Homework] = field(default_factory=list)
    # turn-trace counts (G9 test-traffic caution lives on these)
    turns_total: int = 0
    turns_test_traffic: int = 0
    turns_flagged: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)
    risk_tier_max: str | None = None
    late_night: DependencySignal | None = None
    #: decrypted free text from the window (user turns + homework + notes) — pattern matching
    #: only; NEVER serialized into the packet verbatim.
    pattern_corpus: list[str] = field(default_factory=list)

    @property
    def real_sessions(self) -> list[WindowSession]:
        return [s for s in self.sessions if not s.is_test_traffic]


def window_snapshot(
    *,
    now: _dt.datetime | None = None,
    window_days: int = 7,
    path: Path | None = None,
) -> WindowSnapshot:
    """Assemble the structured window the Shreya-prep packet reads. Degrades to empty."""
    now = now or _dt.datetime.now(_dt.UTC)
    from_ts = _now_iso(now - _dt.timedelta(days=window_days))
    to_ts = _now_iso(now)
    snap = WindowSnapshot(from_ts=from_ts, to_ts=to_ts, window_days=window_days)
    if not telemetry_enabled():
        return snap

    try:
        with _connect(path) as conn:
            sess_rows = conn.execute(
                "SELECT id, started_ts, started_date_ist, started_hour_ist, is_test_traffic "
                "FROM sessions WHERE started_ts >= ? ORDER BY started_ts",
                (from_ts,),
            ).fetchall()
            for sid, started, date_ist, hour_ist, is_test in sess_rows:
                open_mood, close_mood = _session_moods_conn(conn, sid)
                snap.sessions.append(
                    WindowSession(
                        id=sid,
                        started_ts=started,
                        date_ist=date_ist,
                        hour_ist=hour_ist,
                        is_test_traffic=bool(is_test),
                        open_mood=open_mood,
                        close_mood=close_mood,
                    )
                )

            hw_rows = conn.execute(
                "SELECT id, title_enc, assigned_date, due, source_session, status, created_ts "
                "FROM homework WHERE created_ts >= ? ORDER BY created_ts",
                (from_ts,),
            ).fetchall()
            snap.homework = _rows_to_homework(hw_rows)

            trace_rows = conn.execute(
                "SELECT tier, is_test_traffic, safety_action, dependency_action, register_action "
                "FROM turn_traces WHERE ts >= ?",
                (from_ts,),
            ).fetchall()
            for tier, is_test, safety, dep, reg in trace_rows:
                snap.turns_total += 1
                if is_test:
                    snap.turns_test_traffic += 1
                snap.tier_counts[tier] = snap.tier_counts.get(tier, 0) + 1
                if (
                    (safety not in (None, "none"))
                    or (dep not in (None, "clean"))
                    or (reg not in (None, "clean"))
                ):
                    snap.turns_flagged += 1

            corpus: list[str] = []
            for (body_enc,) in conn.execute(
                "SELECT body_enc FROM transcripts WHERE ts >= ? AND role='user'", (from_ts,)
            ).fetchall():
                try:
                    text = crypto.decrypt(body_enc)
                except crypto.CryptoError:
                    continue
                if text:
                    corpus.append(text)
            for (body_enc,) in conn.execute(
                "SELECT body_enc FROM notes WHERE ts >= ?", (from_ts,)
            ).fetchall():
                try:
                    text = crypto.decrypt(body_enc)
                except crypto.CryptoError:
                    continue
                if text:
                    corpus.append(text)
            corpus += [h.title for h in snap.homework if h.title]
            snap.pattern_corpus = corpus
    except sqlite3.Error as exc:
        _log.warning("window_snapshot failed: %s", type(exc).__name__)
        return snap

    rank = {"GREEN": 0, "AMBER": 1, "RED": 2}
    tiers = [t for t in snap.tier_counts if t in rank]
    snap.risk_tier_max = max(tiers, key=lambda t: rank[t]) if tiers else None
    snap.late_night = late_night_signal(now=now, window_days=window_days, path=path)
    return snap


# ---------------------------------------------------------------------------
# Phase 7 — generic date-range reads for the exporter (structured columns only).
# ---------------------------------------------------------------------------


def mood_events_between(
    from_ts: str, to_ts: str, *, path: Path | None = None
) -> list[tuple[str, int]]:
    """(ts, mood) mood chips with ``from_ts <= ts <= to_ts`` (ISO8601 Z), oldest→newest."""
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            return conn.execute(
                "SELECT ts, mood FROM mood_events WHERE ts >= ? AND ts <= ? ORDER BY ts",
                (from_ts, to_ts),
            ).fetchall()
    except sqlite3.Error:
        return []


def turn_tiers_between(
    from_ts: str, to_ts: str, *, path: Path | None = None
) -> list[tuple[str, str]]:
    """(ts, tier) per-turn traces in the window (for risk-event rollups in the export)."""
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            return conn.execute(
                "SELECT ts, tier FROM turn_traces WHERE ts >= ? AND ts <= ? ORDER BY ts",
                (from_ts, to_ts),
            ).fetchall()
    except sqlite3.Error:
        return []


def sessions_between(
    from_ts: str, to_ts: str, *, path: Path | None = None
) -> list[tuple[str, int]]:
    """(id, started_hour_ist) for sessions started within ``from_ts <= started_ts <= to_ts``.

    Unlike :func:`window_snapshot` (a trailing now-anchored window), this honours an explicit
    upper bound so a date-ranged export counts only sessions inside the requested range.
    """
    if not telemetry_enabled():
        return []
    try:
        with _connect(path) as conn:
            return conn.execute(
                "SELECT id, started_hour_ist FROM sessions "
                "WHERE started_ts >= ? AND started_ts <= ? ORDER BY started_ts",
                (from_ts, to_ts),
            ).fetchall()
    except sqlite3.Error:
        return []


def _session_moods_conn(conn: sqlite3.Connection, session_id: str) -> tuple[int | None, int | None]:
    rows = conn.execute(
        "SELECT phase, mood FROM mood_events WHERE session_id=? ORDER BY ts", (session_id,)
    ).fetchall()
    open_mood = close_mood = None
    for phase, mood in rows:
        if phase == "open":
            open_mood = mood
        elif phase == "close":
            close_mood = mood
    return (open_mood, close_mood)
