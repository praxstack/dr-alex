"""G5 delta-banded time-aware re-orientation + G8 loud-staleness helpers.

At session start Dr. Alex prepends a tiny (~20-token) preamble that says, in IST, *when*
we last talked and *what about*, plus a one-line band directive so the model re-enters the
relationship at the right temperature:

  - **< 24h** — same-day, casual continuity ("pick up where we left off").
  - **2–7 days** — re-orient first before diving in.
  - **> 7 days** — it's been a while; gently re-check whether the old frame still fits.

Never forces a callback when ``last_topic`` is empty — a manufactured "last time you said…"
lands as fishing (soul_v1 rule). Adapted from the Hermes daemon delta-preamble (Wave 7).

G8: any derived artifact carries ``generated_at``; the TUI shows a *loud* banner when the
continuity brief is older than 14 days OR an unfinalized-fan-out marker is present. Never
silent decay.
"""

from __future__ import annotations

import datetime as _dt

from dr_alex.timeutil import IST
from dr_alex.timeutil import to_ist as _to_ist_shared

#: G8 threshold — a continuity brief older than this is flagged stale.
STALE_AFTER_DAYS = 14


def _to_ist(now: _dt.datetime) -> _dt.datetime:
    return _to_ist_shared(now)


def parse_iso(value: str | None) -> _dt.datetime | None:
    """Parse an ISO8601 timestamp to an aware UTC datetime (shared by memory/staleness)."""
    if not value:
        return None
    try:
        dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return dt


def _delta_phrase(hours: int) -> str:
    if hours < 1:
        return "under an hour ago"
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _band_directive(hours: int, topic: str) -> str:
    """The one-line persona band. With no topic we never invite a callback (avoids fishing)."""
    has_topic = bool(topic)
    if hours < 24:
        return "Same day — pick up casually where you left off." if has_topic \
            else "Same day — stay light and continuous."
    if hours < 24 * 7:
        return "It's been a few days — re-orient before diving in." if has_topic \
            else "It's been a few days — re-orient gently; don't assume a thread."
    return (
        "It's been a while — gently re-check whether that old frame still fits before "
        "picking it up." if has_topic else
        "It's been a while — open fresh; re-check where things are before assuming anything."
    )


def build_preamble(
    *,
    now: _dt.datetime,
    last_session_at: str | None,
    last_topic: str | None,
) -> str:
    """The ~20-token session-start re-orientation preamble (always includes the IST 'now').

    Returns a compact multi-line string. First line is always the current IST datetime; the
    delta + band lines appear only when we actually have a prior-session timestamp.
    """
    ist_now = _to_ist(now)
    lines = [f"Now: {ist_now.strftime('%A %Y-%m-%d %H:%M')} IST"]

    last_dt = parse_iso(last_session_at)
    if last_dt is not None:
        hours = max(int((ist_now - last_dt.astimezone(IST)).total_seconds() // 3600), 0)
        topic = (last_topic or "").strip()
        if topic:
            lines.append(f'Last talked: {_delta_phrase(hours)} — about: "{topic}".')
        else:
            lines.append(f"Last talked: {_delta_phrase(hours)}.")
        lines.append(_band_directive(hours, topic))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# G8 loud staleness
# ---------------------------------------------------------------------------


def staleness_banner(
    *,
    now: _dt.datetime,
    continuity_generated_at: str | None,
    has_unfinalized: bool,
) -> str | None:
    """A loud one-liner for the TUI when memory may be stale, else None.

    Fires when a prior fan-out did not finish (unfinalized marker present) OR the continuity
    brief is older than :data:`STALE_AFTER_DAYS`.
    """
    if has_unfinalized:
        return (
            "memory may be stale — the last session didn't finish saving; "
            "I'll complete it now."
        )
    gen = parse_iso(continuity_generated_at)
    if gen is None:
        return None
    age_days = (now.astimezone(_dt.UTC) if now.tzinfo else
                now.replace(tzinfo=_dt.UTC)) - gen
    if age_days.days > STALE_AFTER_DAYS:
        return (
            f"memory may be stale — my notes are from {gen.astimezone(IST).strftime('%Y-%m-%d')} "
            f"({age_days.days} days ago). I may be out of date; tell me what's changed."
        )
    return None
