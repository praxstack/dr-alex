"""One home for IST + the UTC/ISO time helpers that used to be re-rolled per module (D13).

Before this module the ``IST = ZoneInfo("Asia/Kolkata")`` constant was defined twice
(``statedb``, ``reorient``) and an identical ``_iso`` / ``_now_iso`` / ``_to_ist`` helper was
copy-pasted across ~8 modules. They now all import from here so the timezone and the wire
format have a single source of truth. Behaviour is byte-identical to the prior copies:
``now_iso`` emits ``%Y-%m-%dT%H:%M:%SZ`` (UTC, trailing Z); naive datetimes are treated as UTC.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

#: India Standard Time — the single canonical constant (was duplicated in statedb + reorient).
IST = ZoneInfo("Asia/Kolkata")


def now_utc(now: _dt.datetime | None = None) -> _dt.datetime:
    """Return ``now`` as an aware UTC datetime (defaulting to the current instant).

    A naive input is interpreted as UTC; an aware input is converted to UTC.
    """
    dt = now or _dt.datetime.now(_dt.UTC)
    return dt.astimezone(_dt.UTC) if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)


def now_iso(now: _dt.datetime | None = None) -> str:
    """UTC ISO8601 with a trailing ``Z`` (``%Y-%m-%dT%H:%M:%SZ``) — the on-wire timestamp."""
    return now_utc(now).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ist(now: _dt.datetime | None = None) -> _dt.datetime:
    """Convert ``now`` (naive = UTC) to an IST-aware datetime."""
    return now_utc(now).astimezone(IST)
