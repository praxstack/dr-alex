"""Device pairing gate (council D3) — the auth boundary between the phone and ``alexd``.

The whole service binds only ``127.0.0.1`` (D3 rider 1), so the only thing that reaches it
is the phone over the Tailscale tailnet. That tunnel is device-identity gated by Tailscale
itself; this module is the *second* gate Prax doesn't have to hold in his head:

  1. ``dr-alex pair`` mints a short, human-typeable **pairing code** — single-use, TTL ≤ 5min,
     rate-limited (lockout after 5 failed redemptions), constant-time compared.
  2. The PWA exchanges the code (once) for a long-lived **device token**. Only the token's
     HMAC is stored server-side; the plaintext is shown/returned exactly once.
  3. Every non-``/crisis``, non-``/healthz`` endpoint requires a valid device token. Tokens
     are scoped (this service only), listable, and revocable from the TUI.

Secrets discipline (Directive 2): codes and tokens are keyed HMACs (``pairing-key`` in the
macOS Keychain via :mod:`dr_alex.crypto`), never stored in the clear, never logged. The store
is its OWN SQLite db (``data/pairing.db``, 0600 under a 0700 dir) — deliberately NOT the
telemetry ``state.db``, so the ``DR_ALEX_TELEMETRY_OFF`` kill-switch can never disable auth.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hmac
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from dr_alex import crypto, timeutil, ulid

_log = logging.getLogger("dr_alex.pairing")

_PAIRING_DB_ENV = "DR_ALEX_PAIRING_DB"
PAIRING_KEY_ACCOUNT = "pairing-key"
_LOCAL_SUBJECT_LABEL = b"dr-alex-local-subject-v1"

#: Pairing-code lifetime — council D3: TTL ≤ 5 minutes.
CODE_TTL_SECONDS = 300
#: Consecutive failed redemptions before a timed lockout (council D3).
MAX_FAILURES = 5
#: How long a lockout lasts once tripped.
LOCKOUT_SECONDS = 900  # 15 minutes

#: Crockford-ish base32 alphabet minus visually ambiguous chars (no I/L/O/U/0/1).
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE_LEN = 8  # ~40 bits; formatted XXXX-XXXX


class PairingLockedOut(RuntimeError):
    """Too many failed pairing attempts — redemption is temporarily locked."""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def pairing_db_path() -> Path:
    override = os.environ.get(_PAIRING_DB_ENV)
    if override:
        return Path(override)
    from dr_alex import paths

    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / "pairing.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairing_codes (
    id          TEXT PRIMARY KEY,
    code_hmac   TEXT NOT NULL,
    created_ts  TEXT NOT NULL,
    expires_ts  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS device_tokens (
    id            TEXT PRIMARY KEY,
    token_hmac    TEXT NOT NULL,
    label         TEXT,
    created_ts    TEXT NOT NULL,
    last_used_ts  TEXT,
    revoked       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pairing_guard (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    failures      INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT
);
"""


def _now(now: _dt.datetime | None = None) -> _dt.datetime:
    dt = now or _dt.datetime.now(_dt.UTC)
    return dt.astimezone(_dt.UTC) if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)


def _iso(dt: _dt.datetime) -> str:
    return timeutil.now_iso(dt)


def _parse(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


@contextmanager
def _connect(path: Path | None = None):
    p = path or pairing_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    existed = p.exists()
    conn = sqlite3.connect(str(p))
    if not existed:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO pairing_guard (id, failures, locked_until) VALUES (1, 0, NULL)"
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _hmac(value: str) -> str:
    key = crypto.load_or_create_secret(
        PAIRING_KEY_ACCOUNT, generator=lambda: secrets.token_bytes(32)
    )
    return hmac.new(key, value.encode("utf-8"), sha256).hexdigest()


def local_subject_id() -> str:
    """Return the stable, server-owned subject for this local installation."""
    key = crypto.load_or_create_secret(
        PAIRING_KEY_ACCOUNT, generator=lambda: secrets.token_bytes(32)
    )
    digest = hmac.new(key, _LOCAL_SUBJECT_LABEL, sha256).digest()[:16]
    return "sub_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# ---------------------------------------------------------------------------
# Pairing codes
# ---------------------------------------------------------------------------


def _format_code(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:]}"


def _canonical_code(code: str) -> str:
    """Uppercase, strip spaces/dashes — so 'abcd-1234' and 'ABCD1234' match."""
    return "".join(ch for ch in code.upper() if ch in _CODE_ALPHABET)


def create_pairing_code(
    *, ttl: int = CODE_TTL_SECONDS, now: _dt.datetime | None = None, path: Path | None = None
) -> str:
    """Mint a single-use pairing code (TTL ≤ 5min). Returns the plaintext (shown once, in TUI)."""
    ttl = max(1, min(int(ttl), CODE_TTL_SECONDS))
    n = _now(now)
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO pairing_codes (id, code_hmac, created_ts, expires_ts, used) VALUES (?,?,?,?,0)",
            (ulid.new(), _hmac(raw), _iso(n), _iso(n + _dt.timedelta(seconds=ttl))),
        )
    _log.info("pairing code minted (ttl=%ds)", ttl)  # body-free: never the code itself
    return _format_code(raw)


def _guard_state(conn: sqlite3.Connection) -> tuple[int, _dt.datetime | None]:
    row = conn.execute("SELECT failures, locked_until FROM pairing_guard WHERE id=1").fetchone()
    return (row[0], _parse(row[1])) if row else (0, None)


@dataclass
class DeviceToken:
    id: str
    token: str  # plaintext — returned exactly once, never persisted


def redeem_pairing_code(
    code: str,
    *,
    label: str | None = None,
    now: _dt.datetime | None = None,
    path: Path | None = None,
) -> DeviceToken | None:
    """Exchange a pairing code for a long-lived device token.

    Constant-time compares against every active, unexpired, unused code. On success the code
    is burned (single-use) and a device token is minted (only its HMAC is stored). On failure
    the consecutive-failure counter increments; at :data:`MAX_FAILURES` redemption is locked
    for :data:`LOCKOUT_SECONDS` (raises :class:`PairingLockedOut`). Returns ``None`` on a plain
    bad/expired code.
    """
    n = _now(now)
    canon = _canonical_code(code or "")
    presented = _hmac(canon) if canon else ""
    # NB: raise ONLY after the `with _connect()` block commits — raising inside it would roll
    # the connection back and silently lose the lockout write (a real bug we hit + fixed).
    raise_locked = False
    result: DeviceToken | None = None
    with _connect(path) as conn:
        failures, locked_until = _guard_state(conn)
        if locked_until is not None and n < locked_until:
            raise_locked = True
        else:
            rows = conn.execute(
                "SELECT id, code_hmac, expires_ts, used FROM pairing_codes"
            ).fetchall()
            matched_id: str | None = None
            for cid, code_hmac, expires_ts, used in rows:
                # constant-time compare on every row (don't early-exit on a mismatch)
                is_match = bool(presented) and hmac.compare_digest(presented, code_hmac)
                exp = _parse(expires_ts)
                fresh = exp is not None and n < exp and not used
                if is_match and fresh:
                    matched_id = cid

            if matched_id is None:
                failures += 1
                locked = failures >= MAX_FAILURES
                new_locked_until = (
                    _iso(n + _dt.timedelta(seconds=LOCKOUT_SECONDS)) if locked else None
                )
                conn.execute(
                    "UPDATE pairing_guard SET failures=?, locked_until=? WHERE id=1",
                    (0 if locked else failures, new_locked_until),
                )
                _log.warning("pairing redemption failed (failures=%d, locked=%s)", failures, locked)
                raise_locked = locked
            else:
                # Success: burn the code, reset the guard, mint the device token.
                conn.execute("UPDATE pairing_codes SET used=1 WHERE id=?", (matched_id,))
                conn.execute("UPDATE pairing_guard SET failures=0, locked_until=NULL WHERE id=1")
                token = secrets.token_urlsafe(32)
                dev_id = ulid.new()
                conn.execute(
                    "INSERT INTO device_tokens (id, token_hmac, label, created_ts, revoked) VALUES (?,?,?,?,0)",
                    (dev_id, _hmac(token), (label or "paired device"), _iso(n)),
                )
                result = DeviceToken(id=dev_id, token=token)
    # -- connection has committed here --
    if raise_locked:
        raise PairingLockedOut("pairing temporarily locked after too many failed attempts")
    if result is not None:
        _log.info("device paired (id=%s)", result.id)
    return result


# ---------------------------------------------------------------------------
# Device tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DevicePrincipal:
    device_id: str
    actor_principal: str


def resolve_device_token(
    token: str | None, *, now: _dt.datetime | None = None, path: Path | None = None
) -> DevicePrincipal | None:
    """Resolve a valid token to its non-revoked paired-device principal."""
    if not token:
        return None
    presented = _hmac(token)
    n = _now(now)
    try:
        with _connect(path) as conn:
            rows = conn.execute("SELECT id, token_hmac, revoked FROM device_tokens").fetchall()
            hit_id: str | None = None
            for did, token_hmac, revoked in rows:
                if not revoked and hmac.compare_digest(presented, token_hmac):
                    hit_id = did
            if hit_id is not None:
                conn.execute(
                    "UPDATE device_tokens SET last_used_ts=? WHERE id=?", (_iso(n), hit_id)
                )
                return DevicePrincipal(hit_id, f"device:{hit_id}")
    except sqlite3.Error:
        return None
    return None


def verify_device_token(
    token: str | None, *, now: _dt.datetime | None = None, path: Path | None = None
) -> bool:
    """True iff ``token`` matches a non-revoked device token (constant-time). Updates last-used."""
    return resolve_device_token(token, now=now, path=path) is not None


@dataclass
class DeviceInfo:
    id: str
    label: str
    created_ts: str
    last_used_ts: str | None
    revoked: bool


def list_devices(*, path: Path | None = None) -> list[DeviceInfo]:
    try:
        with _connect(path) as conn:
            rows = conn.execute(
                "SELECT id, label, created_ts, last_used_ts, revoked FROM device_tokens ORDER BY created_ts"
            ).fetchall()
    except sqlite3.Error:
        return []
    return [
        DeviceInfo(
            id=r[0], label=r[1] or "", created_ts=r[2], last_used_ts=r[3], revoked=bool(r[4])
        )
        for r in rows
    ]


def revoke_device(device_id: str, *, path: Path | None = None) -> bool:
    try:
        with _connect(path) as conn:
            cur = conn.execute(
                "UPDATE device_tokens SET revoked=1 WHERE id=? AND revoked=0", (device_id,)
            )
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def has_any_device(*, path: Path | None = None) -> bool:
    """True if at least one non-revoked device is paired (the PWA is usable)."""
    return any(not d.revoked for d in list_devices(path=path))
