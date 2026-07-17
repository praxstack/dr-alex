"""Session-state JSON persistence: atomicity, 0600 perms, unfinalized marker round-trip."""

from __future__ import annotations

import os
import stat

from dr_alex import statefile
from dr_alex.statefile import SessionState, UnfinalizedMarker


def test_load_missing_is_empty(tmp_path) -> None:
    st = statefile.load(tmp_path / "nope.json")
    assert st == SessionState()


def test_load_corrupt_is_empty(tmp_path) -> None:
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert statefile.load(p) == SessionState()


def test_save_then_load_roundtrip(tmp_path) -> None:
    p = tmp_path / "data" / "session_state.json"
    st = SessionState(last_session_at="2026-07-18T09:00:00Z", last_topic="the 30-min block",
                      continuity_generated_at="2026-07-18T09:00:00Z")
    statefile.save(st, p)
    got = statefile.load(p)
    assert got.last_topic == "the 30-min block"
    assert got.last_session_at == "2026-07-18T09:00:00Z"


def test_save_is_0600_and_dir_0700(tmp_path) -> None:
    p = tmp_path / "data" / "session_state.json"
    statefile.save(SessionState(last_topic="x"), p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700


def test_unfinalized_marker_roundtrip(tmp_path) -> None:
    p = tmp_path / "s.json"
    marker = UnfinalizedMarker(
        session_id="sess1", started_at="2026-07-18T08:00:00Z", end_ts="2026-07-18T09:00:00Z",
        inbox_filename="20260718T090000Z-dr-alex-sess1.md",
        digest={"session_id": "sess1"}, remembered=[0], inbox_written=True,
    )
    statefile.set_unfinalized(marker, p)
    st = statefile.load(p)
    got = st.marker()
    assert got is not None
    assert got.session_id == "sess1"
    assert got.inbox_written is True
    assert got.remembered == [0]

    statefile.clear_unfinalized(p)
    assert statefile.load(p).marker() is None
