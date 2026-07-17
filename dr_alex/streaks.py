"""Gentle, shame-free, BREAKABLE check-in cadence — the anti-addiction streak (item 5).

This is deliberately *not* a habit-forming streak mechanic. Design constraints (persona +
UX, binding):
  - No guilt copy, no "don't break the chain!", no loss-aversion pressure, no compulsion.
  - A break is neutral and expected — the counter simply resets, and the copy stays warm.
  - The number is a soft *cadence* signal (how recently we've been checking in), surfaced
    quietly, never a score to chase.

The computation here is pure: it turns a set of check-in dates into a small
:class:`Cadence` summary. All copy lives in :func:`gentle_line`, which is intentionally
free of streak-pressure language.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Cadence:
    #: Count of consecutive days (ending today or yesterday) with a check-in.
    current: int
    #: The longest such run ever seen (kept for a quiet "you've done this before" note).
    longest: int
    #: Distinct days checked in over the trailing 30 days.
    days_last_30: int
    #: True when today or yesterday has a check-in (the run is "live", not broken).
    active: bool
    last_checkin: _dt.date | None


def _as_dates(dates: Iterable[_dt.date | str]) -> set[_dt.date]:
    out: set[_dt.date] = set()
    for d in dates:
        if isinstance(d, _dt.date):
            out.add(d)
        elif isinstance(d, str) and d:
            try:
                out.add(_dt.date.fromisoformat(d[:10]))
            except ValueError:
                continue
    return out


def compute(checkin_dates: Iterable[_dt.date | str], *, today: _dt.date) -> Cadence:
    """Summarize a set of check-in dates into a :class:`Cadence` as of ``today``.

    A run counts as *current* if it reaches today or yesterday — a single quiet day never
    reads as "broken" (that one-day grace keeps the signal from nagging).
    """
    days = _as_dates(checkin_dates)
    if not days:
        return Cadence(current=0, longest=0, days_last_30=0, active=False, last_checkin=None)

    # Longest consecutive run anywhere in history.
    ordered = sorted(days)
    longest = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)

    # Current run: walk backwards from today (or yesterday, the grace day).
    anchor = today if today in days else (today - _dt.timedelta(days=1))
    current = 0
    if anchor in days:
        d = anchor
        while d in days:
            current += 1
            d -= _dt.timedelta(days=1)
    active = (today in days) or (today - _dt.timedelta(days=1) in days)

    cutoff = today - _dt.timedelta(days=30)
    days_last_30 = sum(1 for d in days if cutoff < d <= today)

    return Cadence(
        current=current,
        longest=max(longest, current),
        days_last_30=days_last_30,
        active=active,
        last_checkin=ordered[-1],
    )


def gentle_line(cadence: Cadence) -> str | None:
    """A quiet, no-pressure cadence line for the TUI, or ``None`` to stay silent.

    Never uses streak-pressure language. Silence is the default for a broken/absent run —
    we do not remind someone that they "lost" anything.
    """
    if cadence.current >= 2 and cadence.active:
        return f"You've checked in {cadence.current} days running — no pressure to keep it going."
    if cadence.days_last_30 >= 3 and not cadence.active:
        # Warm, not guilt-tripping: acknowledge the pattern, invite without obligation.
        return "Good to see you again whenever you drop by — no schedule to keep."
    return None
