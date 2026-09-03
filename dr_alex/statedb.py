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
import logging
import os
import re
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
    is_test_traffic   INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS consent_receipts (
    receipt_id                TEXT PRIMARY KEY,
    subject_id                TEXT NOT NULL,
    actor_principal           TEXT NOT NULL,
    source                    TEXT NOT NULL,
    scope                     TEXT NOT NULL,
    decision                  TEXT NOT NULL,
    effective_at              TEXT NOT NULL,
    expires_at                TEXT,
    policy_version            TEXT NOT NULL,
    copy_version              TEXT NOT NULL,
    retention_policy_version  TEXT NOT NULL,
    purpose_version           TEXT NOT NULL,
    locale                    TEXT NOT NULL,
    acquisition_channel       TEXT NOT NULL,
    supersedes                TEXT
);
CREATE INDEX IF NOT EXISTS consent_receipts_resolution
    ON consent_receipts (subject_id, source, scope, effective_at DESC, receipt_id DESC);
CREATE TABLE IF NOT EXISTS session_owners (
    session_id       TEXT PRIMARY KEY,
    subject_id       TEXT NOT NULL,
    actor_principal  TEXT NOT NULL,
    source           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    ended_at         TEXT
);
CREATE TABLE IF NOT EXISTS finalization_operations (
    operation_id      TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL UNIQUE,
    subject_id        TEXT NOT NULL,
    source            TEXT NOT NULL,
    status            TEXT NOT NULL,
    payload_enc       BLOB,
    step_state        TEXT NOT NULL,
    lease_owner       TEXT,
    lease_generation  INTEGER NOT NULL,
    lease_expires_at  TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    error_class       TEXT
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
        # Apply the 8-table schema only when this db file hasn't been initialized to the
        # current version yet — gated by PRAGMA user_version (D17). Routine reads/writes then
        # skip the CREATE-TABLE script entirely instead of re-running it on every _connect.
        if conn.execute("PRAGMA user_version").fetchone()[0] < _SCHEMA_VERSION:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{_SCHEMA}\nPRAGMA user_version = {_SCHEMA_VERSION};\nCOMMIT;"
            )
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    """Idempotently create the db + schema (perms enforced)."""
    with _connect(path):
        pass


@contextmanager
def _policy_connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Policy-state connection; deliberately independent of the telemetry kill switch."""
    with _connect(path) as conn:
        yield conn


def healthy(path: Path | None = None) -> bool:
    """Read-only liveness probe for ``/healthz``. Never creates, migrates, or writes.

    True when the store is usable OR has simply not been created yet (it is created lazily on
    first real use, so "absent" is not "broken"). False only when the file exists and cannot
    be opened/read — i.e. corrupt, unreadable, or on a dead volume.
    """
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
# Identity-bound policy state (not controlled by DR_ALEX_TELEMETRY_OFF)
# ---------------------------------------------------------------------------


SOURCES = frozenset({"desktop", "pwa", "cli"})
CONSENT_SCOPES = frozenset(
    {
        "transcript_retention",
        "durable_memory",
        "cross_surface_recall",
        "clinical_export",
        "clinical_share",
    }
)
CONSENT_DECISIONS = frozenset({"granted", "denied", "withdrawn"})
_CONSENT_METADATA_KEYS = frozenset(
    {
        "policy_version",
        "copy_version",
        "retention_policy_version",
        "purpose_version",
        "locale",
        "effective_at",
        "expires_at",
    }
)
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_SESSION_ID_RE = re.compile(r"^(?:[0-9A-HJKMNP-TV-Z]{26}|[a-z0-9][a-z0-9.-]{0,127})$")
_MAX_POLICY_VERSION_LENGTH = 32
_MAX_CONSENT_IDENTIFIER_LENGTH = 128
_MAX_LOCALE_LENGTH = 35
_MAX_UTC_TIMESTAMP_LENGTH = 32


class ConsentValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def valid_session_id(value: object) -> bool:
    return isinstance(value, str) and _SESSION_ID_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class ValidatedConsent:
    decisions: dict[str, str]
    effective_at: str
    expires_at: str | None
    policy_version: str
    copy_version: str
    retention_policy_version: str
    purpose_version: str
    locale: str


@dataclass(frozen=True)
class EffectiveConsent:
    transcript_retention: bool = False
    durable_memory: bool = False
    cross_surface_recall: bool = False
    transcript_receipt_id: str | None = None
    durable_receipt_id: str | None = None
    cross_surface_receipt_id: str | None = None
    policy_version: str = "3.0.0"


@dataclass(frozen=True)
class SessionOwner:
    session_id: str
    subject_id: str
    actor_principal: str
    source: str
    created_at: str
    ended_at: str | None = None


@dataclass(frozen=True)
class FinalizationOperation:
    operation_id: str
    session_id: str
    subject_id: str
    source: str
    status: str
    payload_enc: bytes | None
    step_state: str
    lease_owner: str | None
    lease_generation: int
    lease_expires_at: str | None
    error_class: str | None


def _parse_utc(value: object) -> _dt.datetime | None:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_UTC_TIMESTAMP_LENGTH
        or not value.endswith("Z")
    ):
        return None
    try:
        return _dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def _canonical_utc(value: _dt.datetime) -> str:
    return value.astimezone(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_consent_input(
    consent: object,
    *,
    now: _dt.datetime | None = None,
) -> ValidatedConsent:
    if not isinstance(consent, dict):
        raise ConsentValidationError("invalid_consent")
    unknown = set(consent) - CONSENT_SCOPES - _CONSENT_METADATA_KEYS
    if unknown:
        raise ConsentValidationError("unknown_consent_key")
    decisions = {key: value for key, value in consent.items() if key in CONSENT_SCOPES}
    if any(
        not isinstance(value, str) or value not in CONSENT_DECISIONS for value in decisions.values()
    ):
        raise ConsentValidationError("invalid_consent_decision")
    if (
        decisions.get("durable_memory") == "granted"
        and decisions.get("transcript_retention") != "granted"
    ):
        raise ConsentValidationError("durable_requires_transcript_retention")

    required = (
        "policy_version",
        "copy_version",
        "retention_policy_version",
        "purpose_version",
        "locale",
    )
    if any(not isinstance(consent.get(key), str) or not consent[key] for key in required):
        raise ConsentValidationError("invalid_consent_metadata")
    policy_version = consent["policy_version"]
    if len(policy_version) > _MAX_POLICY_VERSION_LENGTH or not _VERSION_RE.fullmatch(
        policy_version
    ):
        raise ConsentValidationError("invalid_policy_version")
    for key in ("copy_version", "retention_policy_version", "purpose_version"):
        if len(consent[key]) > _MAX_CONSENT_IDENTIFIER_LENGTH or not _IDENTIFIER_RE.fullmatch(
            consent[key]
        ):
            raise ConsentValidationError("invalid_consent_metadata")
    if len(consent["locale"]) > _MAX_LOCALE_LENGTH or not _LOCALE_RE.fullmatch(consent["locale"]):
        raise ConsentValidationError("invalid_locale")

    effective_at = consent.get("effective_at", _now_iso(now))
    effective = _parse_utc(effective_at)
    if effective is None:
        raise ConsentValidationError("invalid_effective_at")
    expires_at = consent.get("expires_at")
    expires = _parse_utc(expires_at) if expires_at is not None else None
    if expires_at is not None and (expires is None or expires <= effective):
        raise ConsentValidationError("invalid_expires_at")
    return ValidatedConsent(
        decisions=decisions,
        effective_at=_canonical_utc(effective),
        expires_at=None if expires is None else _canonical_utc(expires),
        policy_version=policy_version,
        copy_version=consent["copy_version"],
        retention_policy_version=consent["retention_policy_version"],
        purpose_version=consent["purpose_version"],
        locale=consent["locale"],
    )


def _record_validated_consent(
    conn: sqlite3.Connection,
    *,
    subject_id: str,
    actor_principal: str,
    source: str,
    validated: ValidatedConsent,
) -> list[str]:
    receipt_ids: list[str] = []
    for scope, decision in validated.decisions.items():
        prior = conn.execute(
            "SELECT receipt_id FROM consent_receipts "
            "WHERE subject_id=? AND source=? AND scope=? "
            "ORDER BY effective_at DESC, receipt_id DESC LIMIT 1",
            (subject_id, source, scope),
        ).fetchone()
        receipt_id = ulid.new()
        conn.execute(
            "INSERT INTO consent_receipts "
            "(receipt_id, subject_id, actor_principal, source, scope, decision, effective_at, "
            "expires_at, policy_version, copy_version, retention_policy_version, purpose_version, "
            "locale, acquisition_channel, supersedes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                receipt_id,
                subject_id,
                actor_principal,
                source,
                scope,
                decision,
                validated.effective_at,
                validated.expires_at,
                validated.policy_version,
                validated.copy_version,
                validated.retention_policy_version,
                validated.purpose_version,
                validated.locale,
                "api_test",
                prior[0] if prior else None,
            ),
        )
        receipt_ids.append(receipt_id)
    return receipt_ids


def _log_consent_decisions(source: str, validated: ValidatedConsent) -> None:
    for scope, decision in sorted(validated.decisions.items()):
        _log.info(
            "event=consent_decision source=%s scope=%s decision=%s count=1",
            source,
            scope,
            decision,
        )


def record_consent(
    *,
    subject_id: str,
    actor_principal: str,
    source: str,
    consent: object,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> list[str]:
    """Validate and atomically store all supplied scope decisions."""
    if source not in SOURCES:
        raise ConsentValidationError("invalid_source")
    validated = validate_consent_input(consent, now=now)
    with _policy_connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        receipt_ids = _record_validated_consent(
            conn,
            subject_id=subject_id,
            actor_principal=actor_principal,
            source=source,
            validated=validated,
        )
    _log_consent_decisions(source, validated)
    return receipt_ids


def resolve_consent(
    subject_id: str,
    source: str,
    *,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> EffectiveConsent:
    """Resolve current consent; every absent, expired, withdrawn, or malformed scope denies."""
    current = timeutil.now_utc(now)
    try:
        with _policy_connect(path) as conn:
            rows = conn.execute(
                "SELECT receipt_id, scope, decision, effective_at, expires_at, policy_version "
                "FROM consent_receipts WHERE subject_id=? AND source=?",
                (subject_id, source),
            ).fetchall()
    except sqlite3.Error as exc:
        _log.warning("consent resolution failed: %s", type(exc).__name__)
        return EffectiveConsent()

    candidates: dict[str, tuple[_dt.datetime, str, bool, str]] = {}
    malformed_scopes: set[str] = set()
    for receipt_id, scope, decision, effective_at, expires_at, policy_version in rows:
        if scope not in CONSENT_SCOPES:
            _log.warning("consent row rejected: unknown_scope")
            continue
        effective = _parse_utc(effective_at)
        if effective is None:
            _log.warning("consent row rejected: invalid_timestamp scope=%s", scope)
            malformed_scopes.add(scope)
            continue
        expires = _parse_utc(expires_at) if expires_at is not None else None
        malformed = (
            (expires_at is not None and expires is None)
            or (expires is not None and expires <= effective)
            or decision not in CONSENT_DECISIONS
            or not isinstance(policy_version, str)
            or not _VERSION_RE.fullmatch(policy_version)
        )
        if malformed:
            _log.warning("consent row rejected: malformed scope=%s", scope)
            malformed_scopes.add(scope)
            continue
        if effective > current:
            continue
        granted = (expires is None or expires > current) and decision == "granted"
        candidate = (effective, receipt_id, granted, policy_version)
        previous = candidates.get(scope)
        if previous is None or candidate[:2] > previous[:2]:
            candidates[scope] = candidate

    resolved: dict[str, tuple[bool, str | None, str]] = {}
    for scope in CONSENT_SCOPES:
        if scope in malformed_scopes:
            resolved[scope] = (False, None, "3.0.0")
            continue
        candidate = candidates.get(scope)
        if candidate is not None:
            _, receipt_id, granted, policy_version = candidate
            resolved[scope] = (granted, receipt_id, policy_version)

    transcript = resolved.get("transcript_retention", (False, None, "3.0.0"))
    durable = resolved.get("durable_memory", (False, None, transcript[2]))
    cross_surface = resolved.get("cross_surface_recall", (False, None, transcript[2]))
    transcript_granted = bool(transcript[0])
    return EffectiveConsent(
        transcript_retention=transcript_granted,
        durable_memory=transcript_granted and bool(durable[0]),
        cross_surface_recall=False,
        transcript_receipt_id=transcript[1],
        durable_receipt_id=durable[1],
        cross_surface_receipt_id=cross_surface[1],
        policy_version=transcript[2],
    )


def _create_session_owner(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    subject_id: str,
    actor_principal: str,
    source: str,
    now: _dt.datetime | None,
) -> SessionOwner | None:
    if not valid_session_id(session_id):
        raise ValueError("invalid session id")
    conn.execute(
        "INSERT OR IGNORE INTO session_owners "
        "(session_id, subject_id, actor_principal, source, created_at, ended_at) "
        "VALUES (?,?,?,?,?,NULL)",
        (session_id, subject_id, actor_principal, source, _now_iso(now)),
    )
    row = conn.execute(
        "SELECT session_id, subject_id, actor_principal, source, created_at, ended_at "
        "FROM session_owners WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if not row or row[1:4] != (subject_id, actor_principal, source) or row[5] is not None:
        return None
    return SessionOwner(*row)


def create_session_owner_and_consent(
    session_id: str,
    *,
    subject_id: str,
    actor_principal: str,
    source: str,
    consent: object | None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> SessionOwner | None:
    """Atomically bind a session owner and optional validated consent receipts."""
    if source not in SOURCES:
        return None
    validated = validate_consent_input(consent, now=now) if consent is not None else None
    with _policy_connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        owner = _create_session_owner(
            conn,
            session_id,
            subject_id=subject_id,
            actor_principal=actor_principal,
            source=source,
            now=now,
        )
        if owner is None:
            conn.rollback()
            return None
        if validated is not None:
            _record_validated_consent(
                conn,
                subject_id=subject_id,
                actor_principal=actor_principal,
                source=source,
                validated=validated,
            )
    if validated is not None:
        _log_consent_decisions(source, validated)
    return owner


def create_session_owner(
    session_id: str,
    *,
    subject_id: str,
    actor_principal: str,
    source: str,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> SessionOwner | None:
    """Create one immutable owner binding, or return its matching active owner."""
    if source not in SOURCES:
        return None
    with _policy_connect(path) as conn:
        return _create_session_owner(
            conn,
            session_id,
            subject_id=subject_id,
            actor_principal=actor_principal,
            source=source,
            now=now,
        )


def get_session_owner(session_id: str, *, path: Path | None = None) -> SessionOwner | None:
    with _policy_connect(path) as conn:
        row = conn.execute(
            "SELECT session_id, subject_id, actor_principal, source, created_at, ended_at "
            "FROM session_owners WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return SessionOwner(*row) if row else None


def close_session_owner(
    session_id: str,
    *,
    subject_id: str,
    actor_principal: str,
    source: str,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> bool:
    """Atomically close the matching active owner binding exactly once."""
    with _policy_connect(path) as conn:
        result = conn.execute(
            "UPDATE session_owners SET ended_at=? WHERE session_id=? AND subject_id=? "
            "AND actor_principal=? AND source=? AND ended_at IS NULL",
            (_now_iso(now), session_id, subject_id, actor_principal, source),
        )
    return result.rowcount == 1


def get_finalization_operation(
    session_id: str, *, path: Path | None = None
) -> FinalizationOperation | None:
    with _policy_connect(path) as conn:
        row = conn.execute(
            "SELECT operation_id,session_id,subject_id,source,status,payload_enc,step_state,"
            "lease_owner,lease_generation,lease_expires_at,error_class "
            "FROM finalization_operations WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return FinalizationOperation(*row) if row else None


def recoverable_finalization_sessions(
    subject_id: str, source: str, *, path: Path | None = None
) -> list[str]:
    """Return this subject's unfinished encrypted operations, oldest first."""
    with _policy_connect(path) as conn:
        rows = conn.execute(
            "SELECT session_id FROM finalization_operations "
            "WHERE subject_id=? AND source=? AND payload_enc IS NOT NULL "
            "AND status IN ('running','recovery_pending','finalization_unavailable') "
            "ORDER BY created_at,operation_id",
            (subject_id, source),
        ).fetchall()
    return [row[0] for row in rows]


def finalization_pending_stats(
    source: str, *, now: _dt.datetime | None = None, path: Path | None = None
) -> tuple[int, int]:
    """Return body-free pending count and oldest age for lifecycle telemetry."""
    with _policy_connect(path) as conn:
        count, oldest = conn.execute(
            "SELECT COUNT(*),MIN(created_at) FROM finalization_operations "
            "WHERE source=? AND payload_enc IS NOT NULL "
            "AND status IN ('running','recovery_pending','finalization_unavailable')",
            (source,),
        ).fetchone()
    parsed = _parse_utc(oldest)
    if not count or parsed is None:
        return int(count or 0), 0
    age = timeutil.now_utc(now) - parsed
    return int(count), max(0, int(age.total_seconds()))


def _lease_window(now: _dt.datetime | None, lease_seconds: int) -> tuple[str, str]:
    lease_now = now or _dt.datetime.now(_dt.UTC)
    if lease_now.tzinfo is None:
        lease_now = lease_now.replace(tzinfo=_dt.UTC)
    current_at = _canonical_utc(lease_now)
    expires_at = _canonical_utc(lease_now + _dt.timedelta(seconds=max(1, min(30, lease_seconds))))
    return current_at, expires_at


def create_finalization(
    session_id: str,
    *,
    subject_id: str,
    source: str,
    status: str,
    payload: str | None = None,
    lease_owner: str | None = None,
    lease_seconds: int | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> FinalizationOperation:
    """Create one encrypted operation, or return the existing operation."""
    timestamp = _now_iso(now)
    lease_expires_at = None
    if lease_owner is not None:
        _, lease_expires_at = _lease_window(now, 5 if lease_seconds is None else lease_seconds)
    payload_enc = crypto.encrypt(payload)
    with _policy_connect(path) as conn:
        conn.execute(
            "INSERT INTO finalization_operations "
            "(operation_id,session_id,subject_id,source,status,payload_enc,step_state,lease_owner,"
            "lease_generation,lease_expires_at,created_at,updated_at,error_class) "
            "VALUES (?,?,?,?,?,?,'{}',?,1,?,?,?,NULL) "
            "ON CONFLICT(session_id) DO NOTHING",
            (
                ulid.new(),
                session_id,
                subject_id,
                source,
                status,
                payload_enc,
                lease_owner,
                lease_expires_at,
                timestamp,
                timestamp,
            ),
        )
        row = conn.execute(
            "SELECT operation_id,session_id,subject_id,source,status,payload_enc,step_state,"
            "lease_owner,lease_generation,lease_expires_at,error_class "
            "FROM finalization_operations WHERE session_id=?",
            (session_id,),
        ).fetchone()
        operation = FinalizationOperation(*row) if row else None
    if operation is None or (operation.subject_id, operation.source) != (subject_id, source):
        raise sqlite3.IntegrityError("finalization owner mismatch")
    return operation


def claim_finalization(
    operation_id: str,
    *,
    lease_owner: str,
    lease_seconds: int = 5,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> bool:
    """Claim one eligible operation by bound ID; never claim a sibling row."""
    current_at, expires_at = _lease_window(now, lease_seconds)
    with _policy_connect(path) as conn:
        result = conn.execute(
            "UPDATE finalization_operations SET status='running',lease_owner=?,"
            "lease_generation=lease_generation+1,lease_expires_at=?,updated_at=? "
            "WHERE operation_id=? "
            "AND status IN ('running','recovery_pending','finalization_unavailable') "
            "AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at<=?)",
            (lease_owner, expires_at, current_at, operation_id, current_at),
        )
    return result.rowcount == 1


def renew_finalization(
    operation_id: str,
    *,
    lease_owner: str,
    lease_generation: int,
    lease_seconds: int = 5,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> bool:
    """Extend one unexpired lease without changing its generation."""
    current_at, expires_at = _lease_window(now, lease_seconds)
    with _policy_connect(path) as conn:
        result = conn.execute(
            "UPDATE finalization_operations SET lease_expires_at=?,updated_at=? "
            "WHERE operation_id=? AND lease_owner=? AND lease_generation=? "
            "AND status='running' AND lease_expires_at>?",
            (
                expires_at,
                current_at,
                operation_id,
                lease_owner,
                lease_generation,
                current_at,
            ),
        )
    return result.rowcount == 1


def update_finalization_fenced(
    operation_id: str,
    *,
    lease_owner: str,
    lease_generation: int,
    step_state: str,
    status: str | None = None,
    payload: str | None = None,
    clear_payload: bool = False,
    release_lease: bool = False,
    error_class: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> bool:
    """Update one running operation only while its exact lease fence still matches."""
    payload_enc = crypto.encrypt(payload) if payload is not None else None
    current_at = _now_iso(now)
    with _policy_connect(path) as conn:
        result = conn.execute(
            "UPDATE finalization_operations SET step_state=?,status=COALESCE(?,status),"
            "payload_enc=CASE WHEN ? THEN NULL WHEN ? THEN ? ELSE payload_enc END,"
            "error_class=?,updated_at=?,"
            "lease_owner=CASE WHEN ? THEN NULL ELSE lease_owner END,"
            "lease_expires_at=CASE WHEN ? THEN NULL ELSE lease_expires_at END "
            "WHERE operation_id=? AND lease_owner=? AND lease_generation=? AND status='running' "
            "AND lease_expires_at>?",
            (
                step_state,
                status,
                clear_payload,
                payload is not None,
                payload_enc,
                error_class,
                current_at,
                release_lease,
                release_lease,
                operation_id,
                lease_owner,
                lease_generation,
                current_at,
            ),
        )
    return result.rowcount == 1


def update_finalization(
    session_id: str,
    *,
    step_state: str,
    status: str | None = None,
    clear_payload: bool = False,
    error_class: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> FinalizationOperation:
    """Persist synthetic progress; completion may atomically erase the replay payload."""
    with _policy_connect(path) as conn:
        result = conn.execute(
            "UPDATE finalization_operations SET step_state=?,status=COALESCE(?,status),"
            "payload_enc=CASE WHEN ? THEN NULL ELSE payload_enc END,error_class=?,updated_at=? "
            "WHERE session_id=?",
            (step_state, status, clear_payload, error_class, _now_iso(now), session_id),
        )
    operation = get_finalization_operation(session_id, path=path)
    if result.rowcount != 1 or operation is None:
        raise sqlite3.IntegrityError("finalization operation missing")
    return operation


# ---------------------------------------------------------------------------
# Sessions / mood / risk telemetry (controlled by DR_ALEX_TELEMETRY_OFF)
# ---------------------------------------------------------------------------


def start_session(
    session_id: str,
    *,
    now: _dt.datetime | None = None,
    is_test_traffic: bool = False,
    path: Path | None = None,
) -> None:
    if not telemetry_enabled():
        return
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


def end_session(
    session_id: str, *, now: _dt.datetime | None = None, path: Path | None = None
) -> None:
    if not telemetry_enabled():
        return
    try:
        with _connect(path) as conn:
            conn.execute("UPDATE sessions SET ended_ts=? WHERE id=?", (_now_iso(now), session_id))
    except sqlite3.Error as exc:
        _log.warning("end_session failed: %s", type(exc).__name__)


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
