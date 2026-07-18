"""D13: the shared IST/time helpers reproduce the prior per-module implementations exactly."""

from __future__ import annotations

import datetime as _dt

from dr_alex import reorient, statedb, timeutil


def _legacy_iso(now: _dt.datetime) -> str:
    dt = now.astimezone(_dt.timezone.utc) if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_one_ist_constant_shared_everywhere() -> None:
    assert timeutil.IST is statedb.IST is reorient.IST
    assert str(timeutil.IST) == "Asia/Kolkata"


def test_now_iso_matches_legacy_for_aware_naive_and_offset() -> None:
    samples = [
        _dt.datetime(2026, 7, 18, 12, 30, 45, tzinfo=_dt.timezone.utc),      # aware UTC
        _dt.datetime(2026, 1, 1, 0, 0, 0),                                   # naive → UTC
        _dt.datetime(2026, 7, 18, 18, 0, 0, tzinfo=timeutil.IST),            # aware IST → UTC
    ]
    for s in samples:
        assert timeutil.now_iso(s) == _legacy_iso(s)


def test_to_ist_matches_legacy() -> None:
    now = _dt.datetime(2026, 7, 18, 20, 30, tzinfo=_dt.timezone.utc)  # 02:00 IST next day
    ist = timeutil.to_ist(now)
    assert ist.tzinfo is timeutil.IST
    assert (ist.hour, ist.minute) == (2, 0)
    # statedb._ist and reorient._to_ist delegate to the same helper.
    assert statedb._ist(now) == ist == reorient._to_ist(now)
