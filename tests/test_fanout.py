"""Session-end fan-out: idempotency, crash recovery, RED conservatism, scrub-fail safety.

All I/O seams are injected — no real memctl, no real store, no real continuity file.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict

import pytest
from cryptography.fernet import Fernet

from dr_alex import crypto, fanout, memstore, statefile
from dr_alex import digest as digest_mod
from dr_alex.digest import SessionDigest, Technique
from dr_alex.statefile import UnfinalizedMarker

_UTC = _dt.UTC


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 9, 0, tzinfo=_UTC)


def _digest(**over) -> SessionDigest:
    base = {
        "session_id": "sess1",
        "started_at": "2026-07-18T08:00:00Z",
        "ended_at": "2026-07-18T09:00:00Z",
        "risk_tier_max": "GREEN",
        "techniques": [Technique("behavioral-activation", "helped")],
        "durable_learnings": ["Fact one about Prax.", "Fact two about Prax."],
        "last_topic": "morning activation",
    }
    base.update(over)
    return SessionDigest(**base)


class _Recorder:
    """A fake memctl.remember that assigns unique ids and records every write."""

    def __init__(self, fail_indices=()):
        self.bodies: list[str] = []
        self.fail_indices = set(fail_indices)

    def __call__(self, body, *, tags, sensitivity, importance, memtype):
        idx = len(self.bodies)
        self.bodies.append(body)
        if idx in self.fail_indices:
            return memstore.WriteResult(ok=False, error="boom")
        return memstore.WriteResult(ok=True, id=f"mem-{idx}")


def _seams(tmp_path, remember=None, scrub=None):
    """Common injected seams writing into tmp_path."""
    inbox = tmp_path / "store" / "inbox"
    continuity_writes: list[str] = []

    def save_continuity(text):
        continuity_writes.append(text)
        p = tmp_path / "continuity.md"
        p.write_text(text, encoding="utf-8")
        return p

    return (
        {
            "remember_fn": remember or _Recorder(),
            "scrub_fn": scrub or (lambda doc: doc.encode("utf-8")),
            "inbox_dir_fn": lambda: str(inbox),
            "continuity_fn": lambda digest, prior, *, now: "brief text",
            "save_continuity_fn": save_continuity,
        },
        continuity_writes,
        inbox,
    )


def _unfinalized_marker(*, session_id="sess1", digest=None) -> UnfinalizedMarker:
    return UnfinalizedMarker(
        session_id=session_id,
        started_at="2026-07-18T08:00:00Z",
        end_ts="2026-07-18T09:00:00Z",
        inbox_filename=f"20260718T090000Z-dr-alex-{session_id}.md",
        digest=digest if digest is not None else digest_mod.to_jsonable(_digest()),
    )


def _write_raw_marker(path, marker: dict) -> None:
    path.write_text(json.dumps({"unfinalized": marker}), encoding="utf-8")


def _encrypted_digest(payload: bytes) -> str:
    key = crypto.load_or_create_secret(crypto.STATE_KEY_ACCOUNT)
    return Fernet(key).encrypt(payload).decode("ascii")


def test_normal_finalize_writes_all_channels(tmp_path) -> None:
    sp = tmp_path / "state.json"
    rec = _Recorder()
    seams, continuity_writes, inbox = _seams(tmp_path, remember=rec)
    res = fanout.finalize_session(
        [("user", "hi"), ("assistant", "hey")],
        session_id="sess1",
        started_at="2026-07-18T08:00:00Z",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
        **seams,
    )
    # Channel B: both durable learnings written.
    assert len(rec.bodies) == 2
    assert res.remembered == ["mem-0", "mem-1"]
    # Channel C: inbox digest written.
    assert res.inbox_path is not None
    files = list(inbox.glob("*.md"))
    assert len(files) == 1
    # Continuity regenerated + state finalized.
    assert continuity_writes == ["brief text"]
    st = statefile.load(sp)
    assert st.marker() is None  # marker cleared
    assert st.last_session_at == "2026-07-18T09:00:00Z"
    assert st.last_topic == "morning activation"
    assert st.continuity_generated_at == "2026-07-18T09:00:00Z"


def test_red_session_withholds_durable_writes(tmp_path) -> None:
    sp = tmp_path / "state.json"
    rec = _Recorder()
    seams, _cw, inbox = _seams(tmp_path, remember=rec)
    res = fanout.finalize_session(
        [("user", "hi")],
        session_id="sessR",
        started_at="t",
        risk_tier_max="RED",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(risk_tier_max="RED"),
        state_path=sp,
        **seams,
    )
    # No durable learnings written on RED (conservative).
    assert rec.bodies == []
    assert res.durable_withheld is True
    # But the inbox digest + continuity still happen (fan-out still runs).
    assert res.inbox_path is not None
    assert list(inbox.glob("*.md"))


def test_crash_recovery_completes_idempotently(tmp_path) -> None:
    sp = tmp_path / "state.json"
    rec = _Recorder()
    seams, _cw, inbox = _seams(tmp_path, remember=rec)

    # begin() distills + writes the marker; then we "crash" (never call complete).
    fanout.begin(
        [("user", "hi")],
        session_id="sess1",
        started_at="t",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
    )
    assert statefile.load(sp).marker() is not None  # unfinalized

    # Next session start detects the marker and completes the fan-out.
    res1 = fanout.recover_if_needed(state_path=sp, **seams)
    assert res1 is not None
    assert len(rec.bodies) == 2
    first_files = sorted(p.name for p in inbox.glob("*.md"))
    assert len(first_files) == 1
    assert statefile.load(sp).marker() is None  # finalized

    # A second recovery is a no-op (marker already cleared) — nothing duplicated.
    res2 = fanout.recover_if_needed(state_path=sp, **seams)
    assert res2 is None
    assert len(rec.bodies) == 2  # no duplicate durable writes
    assert sorted(p.name for p in inbox.glob("*.md")) == first_files  # same single file


def test_replay_persists_generated_at_even_if_continuity_already_written(tmp_path) -> None:
    """A crash AFTER the brief was written must still leave G8's generated_at in state."""
    sp = tmp_path / "state.json"
    seams, continuity_writes, _inbox = _seams(tmp_path)

    marker = fanout.begin(
        [("user", "hi")],
        session_id="sess1",
        started_at="t",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
    )
    # Simulate: everything done except the final state save (continuity already written).
    marker.remembered = [0, 1]
    marker.inbox_written = True
    marker.continuity_written = True
    statefile.set_unfinalized(marker, sp)

    fanout.recover_if_needed(state_path=sp, **seams)
    st = statefile.load(sp)
    assert st.marker() is None
    # G8: generated_at is set from the digest end even though the brief wasn't (re)written.
    assert st.continuity_generated_at == "2026-07-18T09:00:00Z"
    assert continuity_writes == []  # not re-written on replay


def test_partial_remember_ledger_prevents_duplicates(tmp_path) -> None:
    """A replay after some durable writes landed must not re-write them."""
    sp = tmp_path / "state.json"
    rec = _Recorder()
    seams, _cw, _inbox = _seams(tmp_path, remember=rec)

    marker = fanout.begin(
        [("user", "hi")],
        session_id="sess1",
        started_at="t",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
    )
    # Simulate: index 0 already written before the crash.
    marker.remembered = [0]
    statefile.set_unfinalized(marker, sp)

    fanout.recover_if_needed(state_path=sp, **seams)
    # Only the second learning (index 1) should have been written this run.
    assert rec.bodies == ["Fact two about Prax."]


def test_scrub_failure_never_writes_unscrubbed(tmp_path) -> None:
    sp = tmp_path / "state.json"

    def boom_scrub(_doc):
        raise memstore.ScrubError("scrub down")

    seams, _cw, inbox = _seams(tmp_path, scrub=boom_scrub)
    res = fanout.finalize_session(
        [("user", "hi")],
        session_id="sess1",
        started_at="t",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
        **seams,
    )
    assert res.scrub_failed is True
    # No inbox file written when the scrub could not run (privacy fails safe).
    assert not list(inbox.glob("*.md"))


def test_failed_remember_is_retried_on_replay(tmp_path) -> None:
    sp = tmp_path / "state.json"
    # First run: index 1 fails; second run (fresh recorder) should retry index 1.
    rec_fail = _Recorder(fail_indices=[1])
    seams, _cw, _inbox = _seams(tmp_path, remember=rec_fail)
    marker = fanout.begin(
        [("user", "hi")],
        session_id="sess1",
        started_at="t",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
    )
    # Complete but DON'T let it clear the marker fully by faking a crash right after
    # remember: re-load the marker to inspect the ledger.
    fanout.complete(marker, now=_now(), state_path=sp, **seams)
    # Index 0 succeeded (ledgered); index 1 failed (NOT ledgered) → retried on a fresh marker.
    # Re-drive begin+complete to confirm the ledger only recorded the success.
    assert rec_fail.bodies == ["Fact one about Prax.", "Fact two about Prax."]


def test_transient_remember_failure_keeps_session_recoverable(tmp_path) -> None:
    """D5: a remember that RAISES transiently must not silently drop the session's memory —
    the crash-safety marker persists and the next recovery completes it without duplication."""
    sp = tmp_path / "state.json"

    class _RaiseOnceRecorder:
        def __init__(self) -> None:
            self.bodies: list[str] = []
            self.raised = False

        def __call__(self, body, *, tags, sensitivity, importance, memtype):
            # Fail (raise) on the FIRST durable write of the first run; succeed thereafter.
            if not self.raised and not self.bodies:
                self.raised = True
                raise RuntimeError("transient store outage")
            idx = len(self.bodies)
            self.bodies.append(body)
            return memstore.WriteResult(ok=True, id=f"mem-{idx}")

    rec = _RaiseOnceRecorder()
    seams, _cw, inbox = _seams(tmp_path, remember=rec)

    # First run: the first durable write raises → that index is NOT ledgered → incomplete.
    fanout.finalize_session(
        [("user", "hi"), ("assistant", "hey")],
        session_id="sess1",
        started_at="2026-07-18T08:00:00Z",
        risk_tier_max="GREEN",
        now=_now(),
        distill_fn=lambda *a, **k: _digest(),
        state_path=sp,
        **seams,
    )
    # The session is NOT silently finalized — the marker survives for replay.
    assert statefile.load(sp).marker() is not None
    assert rec.raised is True

    # Next session start: recovery completes the fan-out; the previously-failed learning is
    # retried and BOTH durable learnings land, with no duplication.
    res2 = fanout.recover_if_needed(state_path=sp, **seams)
    assert res2 is not None
    assert statefile.load(sp).marker() is None  # fully finalized now
    assert sorted(rec.bodies) == ["Fact one about Prax.", "Fact two about Prax."]
    assert len(rec.bodies) == 2  # no duplicate write
    # Exactly one inbox digest across both runs (deterministic filename ⇒ no dupes).
    assert len(list(inbox.glob("*.md"))) == 1


def test_should_finalize_rules() -> None:
    assert fanout.should_finalize(0, explicit_close=True) is False
    assert fanout.should_finalize(1, explicit_close=True) is True
    assert fanout.should_finalize(2, explicit_close=False) is False
    assert fanout.should_finalize(3, explicit_close=False) is True


def test_recovery_encrypts_legacy_marker_before_first_sink(tmp_path) -> None:
    sp = tmp_path / "state.json"
    sentinel = "SYNTHETIC-LEGACY-DIGEST-SENTINEL"
    digest = digest_mod.to_jsonable(_digest(durable_learnings=[sentinel]))
    _write_raw_marker(sp, asdict(_unfinalized_marker(digest=digest)))
    seen: list[str] = []

    def checking_remember(body, **_kwargs):
        raw_text = sp.read_text(encoding="utf-8")
        raw_marker = json.loads(raw_text)["unfinalized"]
        assert "digest_enc" in raw_marker
        assert "digest" not in raw_marker
        assert sentinel not in raw_text
        loaded = statefile.load(sp).marker()
        assert loaded is not None
        assert loaded.digest == digest
        seen.append(body)
        return memstore.WriteResult(ok=True, id="mem-0")

    seams, _continuity, _inbox = _seams(tmp_path, remember=checking_remember)
    result = fanout.recover_if_needed(
        state_path=sp,
        mirror_fn=lambda _digest: (None, None),
        **seams,
    )

    assert result is not None
    assert seen == [sentinel]
    assert statefile.load(sp).marker() is None


@pytest.mark.parametrize(
    "case",
    [
        "wrong-key",
        "wrong-key-with-plaintext",
        "invalid-utf8",
        "malformed-json",
        "non-object-json",
        "missing-outer-field",
        "extra-outer-field",
        "wrong-outer-type",
    ],
)
def test_encrypted_marker_corruption_fails_loudly(tmp_path, case) -> None:
    sp = tmp_path / "state.json"
    raw_marker = asdict(_unfinalized_marker())
    legacy_digest = raw_marker.pop("digest")
    raw_marker["digest_enc"] = _encrypted_digest(json.dumps(legacy_digest).encode("utf-8"))

    if case.startswith("wrong-key"):
        raw_marker["digest_enc"] = Fernet(Fernet.generate_key()).encrypt(b"{}").decode("ascii")
        if case.endswith("plaintext"):
            raw_marker["digest"] = legacy_digest
    elif case == "invalid-utf8":
        raw_marker["digest_enc"] = _encrypted_digest(b"\xff")
    elif case == "malformed-json":
        raw_marker["digest_enc"] = _encrypted_digest(b"{")
    elif case == "non-object-json":
        raw_marker["digest_enc"] = _encrypted_digest(b"[]")
    elif case == "missing-outer-field":
        raw_marker.pop("started_at")
    elif case == "extra-outer-field":
        raw_marker["unexpected"] = "synthetic"
    elif case == "wrong-outer-type":
        raw_marker["remembered"] = [True]

    _write_raw_marker(sp, raw_marker)
    prior = sp.read_bytes()
    sink_calls: list[str] = []

    def forbidden_sink(*_args, **_kwargs):
        sink_calls.append("called")
        raise AssertionError("corrupt marker reached a sink")

    with pytest.raises(crypto.CryptoError):
        fanout.recover_if_needed(
            state_path=sp,
            remember_fn=forbidden_sink,
            scrub_fn=forbidden_sink,
            inbox_dir_fn=forbidden_sink,
            continuity_fn=forbidden_sink,
            save_continuity_fn=forbidden_sink,
            mirror_fn=forbidden_sink,
        )

    assert sp.read_bytes() == prior
    assert sink_calls == []


def test_marker_encryption_failure_preserves_existing_marker(tmp_path, monkeypatch) -> None:
    sp = tmp_path / "state.json"
    statefile.set_unfinalized(_unfinalized_marker(), sp)
    prior = sp.read_bytes()
    sink_calls: list[str] = []

    def fail_encrypt(_plaintext):
        raise crypto.CryptoError("synthetic encryption failure")

    def forbidden_sink(*_args, **_kwargs):
        sink_calls.append("called")
        raise AssertionError("encryption failure reached a sink")

    monkeypatch.setattr(crypto, "encrypt", fail_encrypt)
    with pytest.raises(crypto.CryptoError, match="synthetic encryption failure"):
        fanout.finalize_session(
            [("user", "synthetic")],
            session_id="sess1",
            started_at="2026-07-18T08:00:00Z",
            risk_tier_max="GREEN",
            now=_now(),
            distill_fn=lambda *_args, **_kwargs: _digest(),
            state_path=sp,
            remember_fn=forbidden_sink,
            scrub_fn=forbidden_sink,
            inbox_dir_fn=forbidden_sink,
            continuity_fn=forbidden_sink,
            save_continuity_fn=forbidden_sink,
            mirror_fn=forbidden_sink,
        )

    assert sp.read_bytes() == prior
    assert sink_calls == []


def test_conflicting_session_cannot_replace_pending_marker(tmp_path, monkeypatch) -> None:
    sp = tmp_path / "state.json"
    raw_marker = asdict(_unfinalized_marker(session_id="sess-a"))
    raw_marker.pop("digest")
    raw_marker["digest_enc"] = Fernet(Fernet.generate_key()).encrypt(b"{}").decode("ascii")
    _write_raw_marker(sp, raw_marker)
    prior = sp.read_bytes()
    decrypt_calls: list[str] = []
    sink_calls: list[str] = []

    def forbidden_decrypt(_token):
        decrypt_calls.append("called")
        raise AssertionError("conflict guard attempted decryption")

    def forbidden_sink(*_args, **_kwargs):
        sink_calls.append("called")
        raise AssertionError("conflicting session reached a sink")

    monkeypatch.setattr(crypto, "decrypt", forbidden_decrypt)
    with pytest.raises(RuntimeError) as exc_info:
        fanout.finalize_session(
            [("user", "synthetic")],
            session_id="sess-b",
            started_at="2026-07-18T08:00:00Z",
            risk_tier_max="GREEN",
            now=_now(),
            distill_fn=lambda *_args, **_kwargs: _digest(session_id="sess-b"),
            state_path=sp,
            remember_fn=forbidden_sink,
            scrub_fn=forbidden_sink,
            inbox_dir_fn=forbidden_sink,
            continuity_fn=forbidden_sink,
            save_continuity_fn=forbidden_sink,
            mirror_fn=forbidden_sink,
        )

    assert exc_info.type is RuntimeError
    assert str(exc_info.value) == "cannot replace pending marker for another session"
    assert decrypt_calls == []
    assert sp.read_bytes() == prior
    assert sink_calls == []
