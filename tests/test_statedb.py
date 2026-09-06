"""state.db: at-rest ciphertext, perms, mood/homework/streaks/traces/repair-ack/G18."""

from __future__ import annotations

import datetime as _dt
import os
import stat

import pytest

from dr_alex import statedb

_UTC = _dt.timezone.utc


def _db(tmp_path):
    return tmp_path / "sub" / "state.db"


# --- at-rest ciphertext (the council D2 headline test) --------------------


def test_freetext_columns_are_ciphertext_at_rest(tmp_path) -> None:
    p = _db(tmp_path)
    secret = "call Shreya about the 3am sleep spiral"
    statedb.add_homework(secret, path=p)
    statedb.record_transcript(
        session_id="s1", role="user", body="I keep RUMINATING at night", path=p
    )

    raw = p.read_bytes()
    # No free-text plaintext is present anywhere in the db file at rest.
    assert secret.encode() not in raw
    assert b"RUMINATING" not in raw
    # But the app-layer decrypt path reads them back cleanly.
    titles = [h.title for h in statedb.open_homework(path=p)]
    assert secret in titles
    turns = statedb.load_transcript("s1", path=p)
    assert any("RUMINATING" in t.body for t in turns)


def test_db_and_dir_perms(tmp_path) -> None:
    p = _db(tmp_path)
    statedb.init_db(p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700


# --- mood ------------------------------------------------------------------


def test_mood_record_and_stats(tmp_path) -> None:
    p = _db(tmp_path)
    base = _dt.datetime(2026, 7, 10, 12, tzinfo=_UTC)
    statedb.record_mood("open", 3, session_id="s1", now=base, path=p)
    statedb.record_mood("close", 6, session_id="s1", now=base + _dt.timedelta(hours=1), path=p)
    stats = statedb.mood_stats(now=base + _dt.timedelta(hours=2), path=p)
    assert stats.points == 2
    assert stats.latest == 6
    assert stats.delta == 3.0


def test_mood_rejects_out_of_range(tmp_path) -> None:
    with pytest.raises(ValueError):
        statedb.record_mood("open", 99, path=_db(tmp_path))
    with pytest.raises(ValueError):
        statedb.record_mood("sideways", 5, path=_db(tmp_path))


def test_daily_mood_has_gaps(tmp_path) -> None:
    p = _db(tmp_path)
    now = _dt.datetime(2026, 7, 18, 6, tzinfo=_UTC)
    statedb.record_mood("open", 5, now=now - _dt.timedelta(days=2), path=p)
    statedb.record_mood("open", 8, now=now, path=p)
    series = statedb.daily_mood(days=30, now=now, path=p)
    assert len(series) == 30
    assert series[-1] == 8.0  # today
    assert series[-3] == 5.0  # two days ago
    assert series[-2] is None  # the gap day


# --- homework --------------------------------------------------------------


def test_homework_lifecycle(tmp_path) -> None:
    p = _db(tmp_path)
    hid = statedb.add_homework("walk 15 min before the standup", source_session="s1", path=p)
    assert hid
    openhw = statedb.open_homework(path=p)
    assert len(openhw) == 1 and openhw[0].title == "walk 15 min before the standup"
    assert statedb.mark_homework_done(hid, path=p) is True
    assert statedb.open_homework(path=p) == []
    assert statedb.all_homework(path=p)[0].status == "done"


# --- G9 traces + streaks + G18 --------------------------------------------


def test_turn_trace_carries_g9_columns(tmp_path) -> None:
    p = _db(tmp_path)
    statedb.record_turn_trace(
        session_id="s1",
        tier="AMBER",
        model_version="claude-fable-5",
        prompt_hash="abc123",
        is_test_traffic=True,
        path=p,
    )
    with statedb._connect(p) as conn:
        row = conn.execute(
            "SELECT model_version, prompt_hash, is_test_traffic FROM turn_traces"
        ).fetchone()
    assert row == ("claude-fable-5", "abc123", 1)


def test_checkin_dates_for_streaks(tmp_path) -> None:
    p = _db(tmp_path)
    # Two sessions same IST day count once; a different day counts separately.
    d1 = _dt.datetime(
        2026, 7, 17, 20, tzinfo=_UTC
    )  # IST next-morning still 17th? 20:00Z = 01:30 IST 18th
    statedb.start_session("a", now=_dt.datetime(2026, 7, 17, 6, tzinfo=_UTC), path=p)
    statedb.start_session("b", now=_dt.datetime(2026, 7, 17, 7, tzinfo=_UTC), path=p)
    statedb.start_session("c", now=_dt.datetime(2026, 7, 18, 6, tzinfo=_UTC), path=p)
    assert statedb.checkin_dates(path=p) == ["2026-07-17", "2026-07-18"]


def test_late_night_signal_flags_clustering(tmp_path) -> None:
    p = _db(tmp_path)
    now = _dt.datetime(2026, 7, 18, 12, tzinfo=_UTC)
    # 02:30 IST == 21:00Z previous day. Three of them in the window → flagged.
    for day in (15, 16, 17):
        statedb.start_session(f"n{day}", now=_dt.datetime(2026, 7, day, 21, tzinfo=_UTC), path=p)
    sig = statedb.late_night_signal(now=now, path=p)
    assert sig.late_night_count == 3
    assert sig.flagged is True


# --- G10 repair-ack --------------------------------------------------------


def test_repair_ack_fires_exactly_once(tmp_path) -> None:
    p = _db(tmp_path)
    statedb.flag_malfunction("empty_reply", session_id="s1", path=p)
    ack = statedb.pending_repair_ack(path=p)
    assert ack is not None and ack.kind == "empty_reply"
    statedb.mark_repair_acked(ack.id, path=p)
    # After acking, nothing is pending — it fires exactly once.
    assert statedb.pending_repair_ack(path=p) is None


def test_repair_ack_collapses_backlog(tmp_path) -> None:
    p = _db(tmp_path)
    statedb.flag_malfunction("empty_reply", path=p)
    statedb.flag_malfunction("llm_error", path=p)
    ack = statedb.pending_repair_ack(path=p)
    statedb.mark_repair_acked(ack.id, path=p)
    # Acking retires the whole backlog — never a pile of stale apologies.
    assert statedb.pending_repair_ack(path=p) is None


# --- kill switch -----------------------------------------------------------


def test_telemetry_off_is_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_TELEMETRY_OFF", "1")
    p = _db(tmp_path)
    assert statedb.record_mood("open", 5, path=p) is None
    assert statedb.add_homework("x", path=p) is None
    assert statedb.open_homework(path=p) == []
    assert not p.exists()  # nothing was ever created


# --- schema applied once, not per-op (D17) ---------------------------------


def test_schema_applied_once_via_user_version(tmp_path) -> None:
    import sqlite3

    p = _db(tmp_path)
    statedb.init_db(p)
    # user_version is stamped, so a second connect skips the CREATE-TABLE script.
    with sqlite3.connect(str(p)) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == statedb._SCHEMA_VERSION
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # All 8 tables are present and further ops keep working (no double-apply error).
    for t in ("sessions", "mood_events", "homework", "turn_traces", "transcripts", "notes"):
        assert t in tables
    statedb.record_mood("open", 5, path=p)
    statedb.record_mood("close", 6, path=p)
    assert statedb.open_homework(path=p) == []  # ops after the guarded schema still succeed


def test_existing_v0_db_upgrades_in_place(tmp_path) -> None:
    """D17 upgrade path: a pre-D17 state.db (tables present, user_version=0) must be
    stamped to the current version on first connect and keep ALL its existing rows —
    the IF-NOT-EXISTS re-apply is a no-op on data, never a wipe."""
    import sqlite3

    p = _db(tmp_path)
    # Simulate the pre-D17 world: full schema applied but NO user_version stamp,
    # with real data already in it.
    statedb.record_mood("open", 4, path=p)
    with sqlite3.connect(str(p)) as c:
        c.execute("PRAGMA user_version = 0")
    with sqlite3.connect(str(p)) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 0
        before = c.execute("SELECT COUNT(*) FROM mood_events").fetchone()[0]
    assert before == 1

    # First op against the v0 file: schema re-applies once (harmless), version stamps.
    statedb.record_mood("close", 7, path=p)
    with sqlite3.connect(str(p)) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == statedb._SCHEMA_VERSION
        after = c.execute("SELECT COUNT(*) FROM mood_events").fetchone()[0]
    assert after == 2  # pre-existing row survived the in-place upgrade


def test_pending_request_retains_assembled_input_and_consumes_fragments_atomically(
    tmp_path,
) -> None:
    p = _db(tmp_path)
    statedb.start_session("s1", path=p)
    assert (
        statedb.record_api_event(
            "fragment-1", session_id="s1", body="earlier", event_type="fragment", path=p
        )
        == "recorded"
    )
    pending = statedb.begin_turn_request(
        "turn-1",
        session_id="s1",
        body="earlier\nfinal",
        fragment_request_ids=["fragment-1"],
        path=p,
    )
    assert pending is not None and pending.input_text == "earlier\nfinal"
    # The assigned fragment is not visible as an independent pending event, avoiding a
    # duplicate injection if the process restarts while this request is still pending.
    assert statedb.load_unconsumed_api_events("s1", path=p) == []
    assert statedb.complete_turn_request(
        "turn-1",
        user_body="earlier\nfinal",
        reply_body="reply",
        tier="GREEN",
        safety_probe_asked=True,
        recent_risk="GREEN",
        path=p,
    )
    assert statedb.load_session_state("s1", path=p).safety_probe_asked is True
    with statedb._connect(p) as conn:
        assert conn.execute(
            "SELECT consumed FROM api_events WHERE request_id='fragment-1'"
        ).fetchone() == (1,)


def test_pending_request_claims_only_coalesced_fragment_ids(tmp_path) -> None:
    p = _db(tmp_path)
    statedb.start_session("s1", path=p)
    assert statedb.record_api_event("old", session_id="s1", body="old", path=p) == "recorded"
    assert statedb.record_api_event("late", session_id="s1", body="late", path=p) == "recorded"
    statedb.begin_turn_request(
        "turn-1",
        session_id="s1",
        body="old\nfinal",
        fragment_request_ids=["old"],
        path=p,
    )
    with statedb._connect(p) as conn:
        rows = conn.execute(
            "SELECT request_id, consumed_by FROM api_events WHERE event_type='fragment' ORDER BY request_id"
        ).fetchall()
    assert rows == [("late", None), ("old", "turn-1")]
