"""Pure helpers: sparkline rendering + the gentle, breakable cadence."""

from __future__ import annotations

import datetime as _dt

from dr_alex import sparkline, streaks, ulid


def test_sparkline_maps_low_and_high() -> None:
    line = sparkline.sparkline([1, 10], lo=1, hi=10)
    assert line[0] == "▁"
    assert line[-1] == "█"


def test_sparkline_gaps_render_as_space() -> None:
    line = sparkline.sparkline([5, None, 5], lo=1, hi=10)
    assert line[1] == " "
    assert len(line) == 3


def test_sparkline_all_empty() -> None:
    assert sparkline.sparkline([None, None, None]) == "   "


def test_cadence_counts_consecutive_days() -> None:
    today = _dt.date(2026, 7, 18)
    dates = [today, today - _dt.timedelta(days=1), today - _dt.timedelta(days=2)]
    cad = streaks.compute(dates, today=today)
    assert cad.current == 3
    assert cad.active is True
    assert streaks.gentle_line(cad) is not None
    # No guilt / no-pressure language.
    assert "no pressure" in streaks.gentle_line(cad).lower()


def test_cadence_break_is_shame_free_silence() -> None:
    today = _dt.date(2026, 7, 18)
    # Last check-in was 5 days ago — the run is broken.
    dates = [today - _dt.timedelta(days=5)]
    cad = streaks.compute(dates, today=today)
    assert cad.current == 0
    assert cad.active is False
    # A single stale check-in stays silent (no nagging).
    assert streaks.gentle_line(cad) is None


def test_cadence_one_day_grace() -> None:
    today = _dt.date(2026, 7, 18)
    dates = [today - _dt.timedelta(days=1), today - _dt.timedelta(days=2)]
    cad = streaks.compute(dates, today=today)
    # Yesterday counts as still-live (a quiet day doesn't read as "broken").
    assert cad.active is True
    assert cad.current == 2


def test_ulid_sorts_by_time_and_is_26_chars() -> None:
    a = ulid.new(now_ms=1000)
    b = ulid.new(now_ms=2000)
    assert len(a) == 26 and len(b) == 26
    assert a < b
