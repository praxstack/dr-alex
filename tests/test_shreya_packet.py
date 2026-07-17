"""G11 Friday Shreya-prep packet: named-pattern read (incl. null cases), G18, fail-loud."""

from __future__ import annotations

import datetime as _dt

from dr_alex import records, shreya_packet, statedb
from dr_alex.records import PatternDoc
from dr_alex.statedb import DependencySignal, WindowSession, WindowSnapshot

_UTC = _dt.timezone.utc


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 9, 0, tzinfo=_UTC)


def _snapshot(**over) -> WindowSnapshot:
    base = dict(
        from_ts="2026-07-11T09:00:00Z", to_ts="2026-07-18T09:00:00Z", window_days=7,
        sessions=[
            WindowSession("01A", "2026-07-16T20:00:00Z", "2026-07-17", 1, False, 3, 6),
            WindowSession("01B", "2026-07-17T20:00:00Z", "2026-07-18", 1, False, 5, 5),
        ],
        turns_total=12, turns_flagged=2, tier_counts={"GREEN": 10, "AMBER": 2},
        risk_tier_max="AMBER",
        late_night=DependencySignal(late_night_count=4, window_days=7, threshold=3, flagged=True),
        pattern_corpus=["I keep doomscrolling at 3am and calling her"],
    )
    base.update(over)
    return WindowSnapshot(**base)


_PATTERNS = [
    PatternDoc("Rumination Loop", ["doomscroll", "3am scroll"]),
    PatternDoc("Avoidance", []),
]


def test_packet_reports_appeared_and_absent_named_patterns() -> None:
    text = shreya_packet.build_packet(_snapshot(), _PATTERNS, now=_now())
    assert "LOCAL DRAFT ONLY" in text  # never-sent banner
    assert "## Headline" in text
    # Rumination matched via its alias "doomscroll"; Avoidance did not.
    surfaced = text.split("Surfaced this window", 1)[1].split("Did NOT surface", 1)[0]
    assert "Rumination Loop" in surfaced
    did_not = text.split("Did NOT surface", 1)[1]
    assert "Avoidance" in did_not
    # The explicit null-flag caution is present.
    assert "probe directly rather than trusting the null flag" in text


def test_packet_surfaces_g18_late_night_and_test_traffic_caution() -> None:
    text = shreya_packet.build_packet(
        _snapshot(turns_test_traffic=3), _PATTERNS, now=_now())
    assert "Late-night dependency signal (G18)" in text
    assert "clustering flagged (G18)" in text
    assert "Test-traffic caution (G9)" in text
    assert "not a clinical signal" in text.lower() or "NOT a clinical signal" in text


def test_packet_self_report_rollup_and_data_sources() -> None:
    text = shreya_packet.build_packet(_snapshot(), _PATTERNS, now=_now())
    assert "Self-Reported State" in text
    assert "3→6/10" in text  # mood chip rollup
    assert "## Data Sources" in text
    assert "state.db" in text  # points at the raw telemetry path
    assert "generated locally and never transmitted" in text


def test_empty_window_headline_flags_the_absence() -> None:
    snap = WindowSnapshot(from_ts="a", to_ts="b", window_days=7)
    text = shreya_packet.build_packet(snap, _PATTERNS, now=_now())
    assert "No real Dr. Alex check-ins this window" in text


def test_no_named_patterns_yet_is_explicit() -> None:
    text = shreya_packet.build_packet(_snapshot(), [], now=_now())
    assert "No named patterns are defined in the Active File yet" in text


def test_generate_is_fail_loud_on_error(monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("snapshot exploded")
    monkeypatch.setattr(statedb, "window_snapshot", boom)
    res = shreya_packet.generate(now=_now(), write=False)
    assert res.ok is False
    assert "PACKET GENERATION FAILED" in res.text
    # The loud placeholder points a human at the raw data paths (Hermes anti-pattern #1/#3).
    assert "state.db" in res.text
    assert "Active-File.md" in res.text


def test_generate_over_real_statedb_window_and_writes_locked_down_file() -> None:
    import os
    import stat

    # Seed a real (throwaway) state.db window: a session with mood chips + homework.
    now = _now()
    statedb.start_session("01LIVE", now=now - _dt.timedelta(hours=2))
    statedb.record_mood("open", 4, session_id="01LIVE", now=now - _dt.timedelta(hours=2))
    statedb.record_mood("close", 7, session_id="01LIVE", now=now - _dt.timedelta(hours=1))
    statedb.add_homework("call Shreya about sleep", source_session="01LIVE", now=now)
    # A named pattern in the Active File that the homework text will match.
    records.ensure_scaffold(now=now)
    p = records.active_file_path()
    text = p.read_text(encoding="utf-8").replace(
        "_No named patterns yet — Prax and Shreya name them here as they emerge._",
        "### Sleep Slippage\naliases: sleep, insomnia\nNight/day inversion.\n",
    )
    p.write_text(text, encoding="utf-8")

    res = shreya_packet.generate(now=now, window_days=7, write=True)
    assert res.ok is True
    assert res.out_path is not None
    assert stat.S_IMODE(os.stat(res.out_path).st_mode) == 0o600
    # The mood chip + the named-pattern match (via "sleep" alias on the homework) show up.
    assert "4→7/10" in res.text
    assert "Sleep Slippage" in res.text.split("Surfaced this window", 1)[1].split("Did NOT", 1)[0]
