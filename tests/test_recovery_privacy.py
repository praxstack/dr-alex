"""Synthetic recovery data stays encrypted, recoverable, and intact on failure."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import traceback
from dataclasses import asdict
from pathlib import Path

import keyring
import pytest
from cryptography.fernet import Fernet

from dr_alex import crypto, fanout, statefile
from dr_alex.digest import SessionDigest

SECRET = "SYNTHETIC_RECOVERY_DIGEST_7ac12"


def _marker():
    return statefile.UnfinalizedMarker(
        session_id="synthetic",
        started_at="2026-01-01T00:00:00Z",
        end_ts="2026-01-01T01:00:00Z",
        inbox_filename="synthetic.md",
        digest={"session_id": "synthetic", "key_insight": SECRET},
        remembered=[0],
        inbox_written=True,
        continuity_written=True,
    )


def _encrypted(marker):
    raw = asdict(marker)
    raw["digest_enc"] = crypto.encrypt(json.dumps(raw.pop("digest"))).decode("ascii")
    return raw


def test_public_begin_encrypts_before_any_state_bytes_reach_disk(tmp_path, monkeypatch):
    target = tmp_path / "session.json"
    writes = []
    real_write = os.write

    def inspect_write(fd, data):
        writes.append(data)
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", inspect_write)
    marker = fanout.begin(
        [("user", "synthetic input")],
        session_id="synthetic",
        started_at="t",
        risk_tier_max="GREEN",
        now=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        distill_fn=lambda *a, **k: SessionDigest(
            session_id="synthetic",
            started_at="t",
            ended_at="t",
            risk_tier_max="GREEN",
            key_insight=SECRET,
        ),
        state_path=target,
    )
    assert writes
    assert all(SECRET.encode() not in data for data in writes)
    assert SECRET not in target.read_text()
    assert statefile.load(target).marker() == marker


@pytest.mark.parametrize("writer", ["save", "update", "set_unfinalized"])
def test_every_state_writer_encrypts_digest(tmp_path, writer):
    target = tmp_path / "session.json"
    marker = _marker()
    if writer == "save":
        statefile.save(statefile.SessionState(unfinalized=asdict(marker)), target)
    elif writer == "update":
        statefile.update(lambda st: setattr(st, "unfinalized", asdict(marker)), target)
    else:
        statefile.set_unfinalized(marker, target)
    assert SECRET not in target.read_text()
    assert statefile.load(target).marker() == marker


def test_legacy_load_migrates_atomically_preserving_all_state(tmp_path, monkeypatch):
    target = tmp_path / "session.json"
    original = {
        "last_session_at": "earlier",
        "last_topic": "neutral",
        "continuity_generated_at": "earlier",
        "unfinalized": asdict(_marker()),
        "human_owned": {"preserve": "exactly"},
    }
    target.write_text(json.dumps(original))
    before = target.read_bytes()
    real_replace = os.replace
    replacements = []

    def inspect_replace(source, destination):
        assert target.read_bytes() == before
        assert SECRET not in Path(source).read_text()
        replacements.append(destination)
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", inspect_replace)
        assert statefile.load(target).marker() == _marker()
    assert len(replacements) == 1
    assert SECRET not in target.read_text()
    statefile.update(lambda st: setattr(st, "last_topic", "updated"), target)
    after = json.loads(target.read_text())
    assert after["human_owned"] == original["human_owned"]
    assert after["last_session_at"] == "earlier"
    assert after["continuity_generated_at"] == "earlier"
    assert statefile.load(target).marker() == _marker()


@pytest.mark.parametrize("failure", ["missing", "wrong", "unavailable"])
def test_key_failure_preserves_pending_marker_and_never_creates_key(tmp_path, monkeypatch, failure):
    target = tmp_path / "session.json"
    target.write_text(json.dumps({"unfinalized": _encrypted(_marker())}))
    before = target.read_bytes()
    crypto.reset_cache()
    created = []

    def get_password(*args):
        if failure == "unavailable":
            raise RuntimeError(SECRET)
        return None if failure == "missing" else base64.b64encode(Fernet.generate_key()).decode()

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "set_password", lambda *args: created.append(True))
    try:
        for operation in (
            lambda: fanout.recover_if_needed(state_path=target),
            lambda: statefile.update(lambda st: setattr(st, "last_topic", "new"), target),
            lambda: statefile.save(statefile.SessionState(), target),
            lambda: statefile.set_unfinalized(_marker(), target),
            lambda: statefile.clear_unfinalized(target),
        ):
            with pytest.raises(crypto.CryptoError) as error:
                operation()
            assert SECRET not in "".join(traceback.format_exception(error.value))
            assert target.read_bytes() == before
        assert created == []
        assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]
    finally:
        crypto.reset_cache()
        monkeypatch.undo()
    assert statefile.load(target).marker() == _marker()


@pytest.mark.parametrize("corruption", ["token", "nonobject", "json", "mixed", "ledger", "shape"])
def test_invalid_encrypted_marker_fails_closed_before_mutation(tmp_path, corruption):
    target = tmp_path / "session.json"
    marker = _encrypted(_marker())
    if corruption == "token":
        marker["digest_enc"] = SECRET
    elif corruption in ("nonobject", "json"):
        body = "[]" if corruption == "nonobject" else SECRET
        marker["digest_enc"] = crypto.encrypt(body).decode()
    elif corruption == "mixed":
        marker["digest"] = {"key_insight": SECRET}
    elif corruption == "ledger":
        marker["remembered"] = [True]
    else:
        marker = [marker]
    target.write_text(json.dumps({"unfinalized": marker}))
    before = target.read_bytes()
    mutations = []
    for operation in (
        lambda: statefile.load(target),
        lambda: statefile.update(lambda st: mutations.append(True), target),
        lambda: statefile.save(statefile.SessionState(), target),
    ):
        with pytest.raises(crypto.CryptoError) as error:
            operation()
        assert SECRET not in "".join(traceback.format_exception(error.value))
        assert target.read_bytes() == before
    assert mutations == []


@pytest.mark.parametrize("failure", ["encrypt", "replace"])
def test_failed_legacy_migration_preserves_original_without_temp_litter(
    tmp_path, monkeypatch, failure
):
    target = tmp_path / "session.json"
    target.write_text(json.dumps({"unfinalized": asdict(_marker()), "last_topic": "neutral"}))
    before = target.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    monkeypatch.setattr(
        crypto if failure == "encrypt" else os,
        "encrypt" if failure == "encrypt" else "replace",
        fail,
    )
    with pytest.raises((crypto.CryptoError, OSError)):
        statefile.load(target)
    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_update_cannot_overwrite_corrupt_outer_state(tmp_path):
    target = tmp_path / "session.json"
    target.write_text('{"unfinalized":')
    before = target.read_bytes()
    with pytest.raises(crypto.CryptoError):
        statefile.clear_unfinalized(target)
    assert target.read_bytes() == before
