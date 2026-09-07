"""Session-state JSON persistence: atomicity, 0600 perms, unfinalized marker round-trip."""

from __future__ import annotations

import json
import os
import stat
import threading

import pytest

from dr_alex import statefile
from dr_alex.statefile import SessionState, UnfinalizedMarker


def _marker(session_id: str) -> UnfinalizedMarker:
    return UnfinalizedMarker(
        session_id=session_id,
        started_at="2026-07-18T08:00:00Z",
        end_ts="2026-07-18T09:00:00Z",
        inbox_filename=f"{session_id}.md",
        digest={"session_id": session_id, "key_insight": "synthetic"},
    )


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


def test_set_unfinalized_rejects_a_different_pending_session_without_writing(tmp_path) -> None:
    p = tmp_path / "s.json"
    statefile.set_unfinalized(_marker("A"), p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["last_topic"] = "preserve"
    raw["unrelated"] = {"sentinel": "keep"}
    p.write_text(json.dumps(raw), encoding="utf-8")
    before = p.read_bytes()

    with pytest.raises(RuntimeError) as error:
        statefile.set_unfinalized(_marker("B"), p)

    message = str(error.value)
    assert "A" not in message and "B" not in message
    assert "synthetic" not in message and "key" not in message
    assert p.read_bytes() == before
    assert statefile.load(p).marker().session_id == "A"
    assert statefile.load(p).last_topic == "preserve"
    assert json.loads(p.read_text(encoding="utf-8"))["unrelated"] == {"sentinel": "keep"}


def test_set_unfinalized_accepts_same_session_progress(tmp_path) -> None:
    p = tmp_path / "s.json"
    statefile.set_unfinalized(_marker("A"), p)
    retry = _marker("A")
    retry.remembered = [0]

    statefile.set_unfinalized(retry, p)

    assert statefile.load(p).marker().remembered == [0]


def test_set_unfinalized_race_accepts_one_session_and_preserves_its_marker(tmp_path) -> None:
    p = tmp_path / "s.json"
    start = threading.Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def write(session_id: str) -> None:
        try:
            start.wait(timeout=5)
            statefile.set_unfinalized(_marker(session_id), p)
            outcomes.append(session_id)
        except RuntimeError:
            outcomes.append("rejected")
        except BaseException as error:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(error)

    threads = [
        threading.Thread(target=write, args=(session_id,), daemon=True) for session_id in ("A", "B")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads), "setter race deadlocked"
    assert not errors, errors
    assert sorted(outcomes) == ["A", "rejected"] or sorted(outcomes) == ["B", "rejected"]
    assert statefile.load(p).marker().session_id in {"A", "B"}
