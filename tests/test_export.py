"""Date-ranged export (council D6): redaction, locked-down files, date-only names, SVG chart."""

from __future__ import annotations

import datetime as _dt
import os
import stat

from dr_alex import export, records, statedb
from dr_alex.digest import SessionDigest, Technique

_UTC = _dt.timezone.utc

_FROM = "2026-07-01"
_TO = "2026-07-18"
_SECRET_HW = "SECRETHW-message-the-ex-at-3am"
_SECRET_INSIGHT = "SECRETINSIGHT-heroic-leaps-then-collapse"


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 12, 0, tzinfo=_UTC)


def _seed() -> None:
    statedb.record_mood("open", 3, session_id="01A", now=_dt.datetime(2026, 7, 15, 8, tzinfo=_UTC))
    statedb.record_mood("close", 6, session_id="01A", now=_dt.datetime(2026, 7, 15, 9, tzinfo=_UTC))
    statedb.record_mood("open", 4, session_id="01M", now=_dt.datetime(2026, 7, 16, 8, tzinfo=_UTC))
    statedb.record_mood("open", 5, session_id="01B", now=_dt.datetime(2026, 7, 17, 8, tzinfo=_UTC))
    statedb.add_homework(_SECRET_HW, source_session="01A", now=_dt.datetime(2026, 7, 15, 8, tzinfo=_UTC))
    statedb.record_turn_trace(
        session_id="01A", tier="AMBER", model_version="m", prompt_hash="h",
        is_test_traffic=False, now=_dt.datetime(2026, 7, 16, 10, tzinfo=_UTC),
    )
    # A session-log entry with a private insight, dated inside the window.
    records.update_from_digest(SessionDigest(
        session_id="01A", started_at="2026-07-16T08:00:00Z", ended_at="2026-07-16T09:00:00Z",
        risk_tier_max="AMBER", mood_in=3, mood_out=6,
        techniques=[Technique("behavioral-activation", "helped")],
        key_insight=_SECRET_INSIGHT,
    ), now=_dt.datetime(2026, 7, 16, 9, tzinfo=_UTC))


def test_export_writes_locked_down_files_with_date_only_names() -> None:
    _seed()
    res = export.export_range(_FROM, _TO, redaction="summary", now=_now(), write=True)
    assert res.ok
    for p in (res.markdown_path, res.html_path):
        assert p is not None and os.path.exists(p)
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    # Exports dir is 0700.
    assert stat.S_IMODE(os.stat(os.path.dirname(res.markdown_path)).st_mode) == 0o700
    # Filenames carry the date range only — no clinical content.
    assert os.path.basename(res.markdown_path) == f"dr-alex-{_FROM}_{_TO}-summary.md"
    assert _SECRET_HW not in res.markdown_path and _SECRET_INSIGHT not in res.markdown_path


def test_summary_redaction_omits_verbatim_full_includes_it() -> None:
    _seed()
    summ = export.export_range(_FROM, _TO, redaction="summary", now=_now(), write=False)
    assert _SECRET_HW not in summ.markdown and _SECRET_HW not in summ.html
    assert _SECRET_INSIGHT not in summ.markdown and _SECRET_INSIGHT not in summ.html
    # But the counts/trend are still there.
    assert "mean" in summ.markdown.lower()

    full = export.export_range(_FROM, _TO, redaction="full", now=_now(), write=False)
    assert _SECRET_HW in full.markdown and _SECRET_HW in full.html
    assert _SECRET_INSIGHT in full.markdown and _SECRET_INSIGHT in full.html


def test_export_has_inline_svg_mood_chart() -> None:
    _seed()
    res = export.export_range(_FROM, _TO, redaction="summary", now=_now(), write=False)
    assert "<svg" in res.html
    assert "<polyline" in res.html  # the mood line (we seeded ≥2 points)
    assert "AMBER" in res.html  # the risk rollup


def test_bad_dates_fail_cleanly() -> None:
    res = export.export_range("not-a-date", _TO, now=_now(), write=False)
    assert res.ok is False and "bad date" in (res.error or "")


def test_review_defaults_to_last_30_days() -> None:
    _seed()
    res = export.review(days=30, now=_now(), write=False)
    assert res.ok
    assert res.to_date == "2026-07-18"
    assert res.from_date == "2026-06-18"


def test_mood_svg_handles_empty_series() -> None:
    svg = export.mood_svg([("2026-07-01", None), ("2026-07-02", None)])
    assert "<svg" in svg
    assert "no mood chips" in svg  # honest empty-state, not a fabricated line
