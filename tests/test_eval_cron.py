"""G13 nightly eval (mocked judge): scores only, relative drift, liveness, R3 log hygiene."""

from __future__ import annotations

import datetime as _dt
import logging

from dr_alex import eval_cron, statedb

_UTC = _dt.timezone.utc


def _seed_session(p, sid, body):
    statedb.record_transcript(session_id=sid, role="user", body=body, tier="GREEN", path=p)
    statedb.record_transcript(session_id=sid, role="assistant", body="I hear you.", path=p)


def test_scores_only_and_no_transcript_leaks(tmp_path, caplog) -> None:
    p = tmp_path / "state.db"
    _seed_session(p, "s1", "SECRET_TRANSCRIPT_BODY that must never be logged")

    with caplog.at_level(logging.INFO, logger="dr_alex.eval"):
        res = eval_cron.run_eval(now=_dt.datetime(2026, 7, 18, tzinfo=_UTC),
                                 judge_fn=lambda text: 5.5, path=p)
    assert len(res.scored) == 1 and res.scored[0].score == 5.5
    # ONLY the score was logged; the transcript body never appears (R3).
    assert "SECRET_TRANSCRIPT_BODY" not in caplog.text
    assert "5.5" in caplog.text
    # The score is persisted; the transcript stays encrypted in the db (never to disk plainly).
    assert statedb.recent_eval_scores(path=p) == [5.5]


def test_relative_drift_alarm(tmp_path) -> None:
    p = tmp_path / "state.db"
    # A stable recent history around 6.0 (attached to already-scored sessions).
    for i, v in enumerate([6.0, 6.1, 5.9, 6.0, 6.2]):
        statedb.record_eval_score(v, session_id=f"old{i}", path=p)
    _seed_session(p, "newlow", "a rough session")

    res = eval_cron.run_eval(now=_dt.datetime(2026, 7, 18, tzinfo=_UTC),
                             judge_fn=lambda text: 1.0, path=p)
    assert res.scored[0].drift_flagged is True
    assert res.drift_alarms


def test_only_unscored_sessions_are_evaluated(tmp_path) -> None:
    p = tmp_path / "state.db"
    _seed_session(p, "s1", "hi")
    calls = {"n": 0}

    def judge(text):
        calls["n"] += 1
        return 5.0

    eval_cron.run_eval(judge_fn=judge, path=p)
    eval_cron.run_eval(judge_fn=judge, path=p)  # s1 already scored → skipped
    assert calls["n"] == 1


def test_liveness_quiet_week_is_silent(tmp_path) -> None:
    p = tmp_path / "state.db"
    # No sessions at all → an honest quiet week, not a blind watchdog.
    assert eval_cron.liveness(now=_dt.datetime(2026, 7, 18, tzinfo=_UTC), path=p) is None


def test_liveness_flags_blind_watchdog(tmp_path) -> None:
    p = tmp_path / "state.db"
    _seed_session(p, "waiting", "unscored input is piling up")
    # Never scored + input waiting → loud.
    banner = eval_cron.liveness(now=_dt.datetime(2026, 7, 18, tzinfo=_UTC), path=p)
    assert banner is not None and "blind" in banner.lower()


def test_disabled_telemetry_does_not_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_TELEMETRY_OFF", "1")
    res = eval_cron.run_eval(judge_fn=lambda t: 5.0, path=tmp_path / "state.db")
    assert res.ran is False
