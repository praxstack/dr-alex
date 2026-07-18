"""Telemetry facade — the thin seam the engine/TUI use to talk to ``state.db``.

Bundles the pieces that don't belong in the raw store: the G9 turn-provenance helpers
(``model_version`` + ``prompt_hash`` + ``is_test_traffic``), the real 30-day mood trend that
fills the Phase-3 ``MoodRiskTrend`` seam, and the G10 one-time repair-ack orchestration.

Everything degrades safely: with telemetry disabled (or a broken store) the trend falls back
to honest emptiness and the ack helpers become no-ops.
"""

from __future__ import annotations

import datetime as _dt
import os
from hashlib import sha256

from dr_alex import memory as _memory
from dr_alex import statedb

_MODEL_ENV = "DR_ALEX_MODEL"
_TEST_TRAFFIC_ENV = "DR_ALEX_TEST_TRAFFIC"


def enabled() -> bool:
    return statedb.telemetry_enabled()


# ---------------------------------------------------------------------------
# G9 — turn provenance (a wrong model ran for a month at Hermes, undetected).
# ---------------------------------------------------------------------------


def model_version() -> str:
    """The model identifier for this run (``DR_ALEX_MODEL`` if pinned, else the CLI default)."""
    return os.environ.get(_MODEL_ENV) or "claude-cli-default"


def prompt_hash(system_prompt: str, user_prompt: str) -> str:
    """A stable hash of the exact prompt shape — NOT the body (R3). 16 hex chars is plenty."""
    h = sha256()
    h.update(system_prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(user_prompt.encode("utf-8"))
    return h.hexdigest()[:16]


def is_test_traffic() -> bool:
    """True when this session is synthetic/test traffic (``DR_ALEX_TEST_TRAFFIC``)."""
    return os.environ.get(_TEST_TRAFFIC_ENV, "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# The real 30-day mood/risk trend — fills the Phase-3 MoodRiskTrend seam.
# ---------------------------------------------------------------------------


def real_trend(*, now: _dt.datetime | None = None) -> _memory.MoodRiskTrend:
    now = now or _dt.datetime.now(_dt.UTC)
    stats = statedb.mood_stats(days=30, now=now)
    if stats.points == 0:
        return _memory.MoodRiskTrend(available=False)
    return _memory.MoodRiskTrend(
        available=True,
        window_days=stats.window_days,
        mood_points=stats.points,
        mood_latest=stats.latest,
        mood_mean=stats.mean,
        mood_delta=stats.delta,
        risk_tier_max=statedb.risk_tier_max(days=30, now=now),
    )


def trend_seam():
    """Return the trend function the engine should use (real when telemetry is on)."""
    return real_trend if enabled() else _memory.stub_trend


# ---------------------------------------------------------------------------
# G10 — one-time repair-ack after a visible malfunction.
# ---------------------------------------------------------------------------

_ACK_COPY = {
    "empty_reply": (
        "Quick note before we start: last time I left you with a blank reply — that was a "
        "glitch on my end, not you. I'm here properly now."
    ),
    "wrong_crisis_card": (
        "One thing first: last time I threw a crisis card at you when it didn't fit. That "
        "was my mistake, and I'm sorry it landed that way. I'm listening now."
    ),
    "llm_error": (
        "Before we dive in: last time you saw an error where my reply should've been. That "
        "was a hiccup on my end. All good now."
    ),
}


def note_malfunction(kind: str, *, session_id: str | None = None, now: _dt.datetime | None = None) -> None:
    """Record a visible malfunction so exactly one ack is queued for the next session start."""
    statedb.flag_malfunction(kind, session_id=session_id, now=now)


def take_repair_ack(*, now: _dt.datetime | None = None) -> str | None:
    """Return ONE brief acknowledgment for a pending malfunction (and retire it), else None.

    Fires exactly once per malfunction and NEVER on a crisis turn — callers only invoke this
    at a calm session start, never from the RED path.
    """
    ack = statedb.pending_repair_ack()
    if ack is None:
        return None
    statedb.mark_repair_acked(ack.id, now=now)
    return _ACK_COPY.get(ack.kind, _ACK_COPY["llm_error"])
