"""G5 delta-banded re-orientation preamble + G8 loud-staleness helpers."""

from __future__ import annotations

import datetime as _dt

from dr_alex import reorient

_UTC = _dt.timezone.utc


def _now() -> _dt.datetime:
    # 2026-07-18 09:00 UTC == 14:30 IST (a Saturday).
    return _dt.datetime(2026, 7, 18, 9, 0, tzinfo=_UTC)


def test_preamble_always_carries_ist_now() -> None:
    p = reorient.build_preamble(now=_now(), last_session_at=None, last_topic=None)
    assert "IST" in p
    assert "14:30" in p  # 09:00 UTC -> 14:30 IST
    # No prior session -> no fabricated callback line.
    assert "Last talked" not in p


def test_band_same_day_casual() -> None:
    last = (_now() - _dt.timedelta(hours=5)).isoformat()
    p = reorient.build_preamble(now=_now(), last_session_at=last, last_topic="the 30-min block")
    assert "5h ago" in p
    assert 'about: "the 30-min block"' in p
    assert "Same day" in p


def test_band_re_orient_2_to_7_days() -> None:
    last = (_now() - _dt.timedelta(days=3)).isoformat()
    p = reorient.build_preamble(now=_now(), last_session_at=last, last_topic="avoidance around DSA")
    assert "3d ago" in p
    assert "re-orient" in p.lower()


def test_band_recheck_frame_over_7_days() -> None:
    last = (_now() - _dt.timedelta(days=12)).isoformat()
    p = reorient.build_preamble(now=_now(), last_session_at=last, last_topic="the shame spiral")
    assert "12d ago" in p
    assert "been a while" in p.lower()
    assert "frame" in p.lower()


def test_empty_topic_never_forces_a_callback() -> None:
    last = (_now() - _dt.timedelta(days=3)).isoformat()
    p = reorient.build_preamble(now=_now(), last_session_at=last, last_topic="")
    assert "3d ago" in p
    assert "about:" not in p  # no manufactured "about X"
    # And the band directive must not invite a callback on an empty thread.
    assert "don't assume a thread" in p


def test_staleness_banner_fires_on_unfinalized() -> None:
    b = reorient.staleness_banner(now=_now(), continuity_generated_at=None, has_unfinalized=True)
    assert b is not None
    assert "stale" in b.lower()


def test_staleness_banner_fires_when_brief_old() -> None:
    old = (_now() - _dt.timedelta(days=20)).isoformat()
    b = reorient.staleness_banner(now=_now(), continuity_generated_at=old, has_unfinalized=False)
    assert b is not None
    assert "stale" in b.lower()


def test_staleness_banner_silent_when_fresh() -> None:
    fresh = (_now() - _dt.timedelta(days=2)).isoformat()
    b = reorient.staleness_banner(now=_now(), continuity_generated_at=fresh, has_unfinalized=False)
    assert b is None
