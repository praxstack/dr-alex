"""Canonical clinical files are replaced atomically — a failed write never empties them.

``records/Active-File.md`` holds the hand-authored, human-owned sections (Identity, Living
Pattern Docs, Medication Timeline) and has NO backup: ``records/`` is gitignored and the G19
bundle only carries tracked refs. It is also read-modify-write — ``update_from_digest`` reads
the file and rebuilds any missing section from defaults — so a truncate-in-place write that
then failed would not merely lose the file, it would let the NEXT session silently overwrite
the human-owned sections with defaults. Same story for the continuity brief.
"""

from __future__ import annotations

import os
import stat

import pytest

from dr_alex import continuity, records


def _boom(*_a, **_k):
    raise OSError("ENOSPC")


def test_records_write_failure_leaves_the_previous_file_intact(tmp_path, monkeypatch) -> None:
    p = tmp_path / "records" / "Active-File.md"
    records._write(p, "ORIGINAL hand-authored pattern docs")
    assert p.read_text(encoding="utf-8") == "ORIGINAL hand-authored pattern docs"

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        records._write(p, "replacement that never lands")

    # NOT empty, NOT truncated — the old canonical record survives untouched.
    assert p.read_text(encoding="utf-8") == "ORIGINAL hand-authored pattern docs"


def test_records_write_leaves_no_temp_litter_on_success(tmp_path) -> None:
    p = tmp_path / "records" / "Active-File.md"
    records._write(p, "one")
    records._write(p, "two")
    assert p.read_text(encoding="utf-8") == "two"
    assert sorted(q.name for q in p.parent.iterdir()) == ["Active-File.md"]


def test_records_write_keeps_0600_and_dir_0700(tmp_path) -> None:
    p = tmp_path / "records" / "Active-File.md"
    records._write(p, "x")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700
    records._write(p, "y")  # perms hold across a replace, not just on create
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_human_owned_sections_survive_a_failed_write(tmp_path, monkeypatch) -> None:
    """The amplification that makes this MAJOR rather than cosmetic."""
    p = tmp_path / "records" / "Active-File.md"
    records.ensure_scaffold(path=p)
    seeded = records.read_text(p).replace(
        "_No named patterns yet — Prax and Shreya name them here as they emerge._",
        "### The 30-minute block\nNamed with Shreya on week 6.",
    )
    records._write(p, seeded)

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        records._write(p, "clobber")
    monkeypatch.undo()

    assert "### The 30-minute block" in records.read_text(p)


def test_continuity_write_failure_leaves_the_previous_brief_intact(tmp_path, monkeypatch) -> None:
    target = tmp_path / "data" / "continuity.md"
    monkeypatch.setattr(continuity, "continuity_write_path", lambda: target)

    continuity.save_continuity_text("where we left off: the one small step")
    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        continuity.save_continuity_text("replacement that never lands")

    assert target.read_text(encoding="utf-8") == "where we left off: the one small step"


def test_continuity_write_is_0600_and_leaves_no_litter(tmp_path, monkeypatch) -> None:
    target = tmp_path / "data" / "continuity.md"
    monkeypatch.setattr(continuity, "continuity_write_path", lambda: target)
    continuity.save_continuity_text("a")
    continuity.save_continuity_text("b")
    assert target.read_text(encoding="utf-8") == "b"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert sorted(q.name for q in target.parent.iterdir()) == ["continuity.md"]


def test_statefile_save_never_double_closes_its_fd(tmp_path, monkeypatch) -> None:
    """A second ``os.close`` on the error path could close an UNRELATED, recycled fd."""
    from dr_alex import statefile

    p = tmp_path / "data" / "session_state.json"
    closed: list[int] = []
    real_close = os.close

    def _tracking_close(fd):
        closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "close", _tracking_close)
    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        statefile.save(statefile.SessionState(last_topic="x"), p)

    assert len(closed) == len(set(closed)), f"fd closed twice: {closed}"


def test_statefile_save_survives_an_unsupported_fsync(tmp_path, monkeypatch) -> None:
    """fsync is BEST-EFFORT: it must never become a new raise point on the fan-out path."""
    from dr_alex import statefile

    p = tmp_path / "data" / "session_state.json"
    monkeypatch.setattr(os, "fsync", _boom)
    statefile.save(statefile.SessionState(last_topic="the 30-min block"), p)
    assert statefile.load(p).last_topic == "the 30-min block"


def test_update_is_a_true_lost_update_test(tmp_path):
    """Two threads incrementing the SAME field must both be counted.

    The earlier version of this test had each thread write a DIFFERENT field, so a lost
    update was undetectable and the assertion held even with no locking at all. This
    version fails loudly if `update()` ever stops holding the lock across load→mutate→save:
    an unlocked read-modify-write drops increments and the final count comes in under 2N.
    """
    import threading

    from dr_alex import statefile

    p = tmp_path / "session_state.json"
    statefile.save(statefile.SessionState(last_topic="0"), p)

    N = 75
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def bump() -> None:
        try:
            start.wait(timeout=5)
            for _ in range(N):
                statefile.update(
                    lambda st: setattr(st, "last_topic", str(int(st.last_topic or "0") + 1)), p
                )
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=bump, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # A deadlock must FAIL, not silently pass by timing out the join.
    assert not any(t.is_alive() for t in threads), "update() deadlocked"
    assert not errors, errors
    assert int(statefile.load(p).last_topic) == 2 * N, "lost update: the lock is not held across RMW"


def test_finalize_state_uses_atomic_update(tmp_path):
    """fanout._finalize_state must not hand-roll load/mutate/save."""
    import inspect

    from dr_alex import fanout

    src = inspect.getsource(fanout._finalize_state)
    assert "statefile.update(" in src, "must use the atomic RMW API"
    assert "statefile.save(" not in src, "hand-rolled save reintroduces the race"


def test_keep_marker_path_touches_nothing(tmp_path):
    """keep_marker=True must not read or write the state file at all."""
    from types import SimpleNamespace

    from dr_alex import fanout, statefile

    p = tmp_path / "session_state.json"
    marker = statefile.UnfinalizedMarker(
        session_id="s1", started_at="t", end_ts="t", inbox_filename="f"
    )
    statefile.set_unfinalized(marker, p)
    before = p.read_text(encoding="utf-8")

    digest = SimpleNamespace(ended_at="2026-07-26T00:00:00Z", last_topic="x")
    fanout._finalize_state(marker, digest, p, keep_marker=True)

    assert p.read_text(encoding="utf-8") == before, "keep_marker path must be a no-op on disk"
