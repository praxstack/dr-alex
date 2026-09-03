"""The memctl bridge: identity, argv construction, importance clamp, honest degradation.

These never spawn a real subprocess — ``memstore._run`` is monkeypatched to capture argv.
"""

from __future__ import annotations

import json

import pytest

from dr_alex import captoken, memstore
from dr_alex.memstore import _Proc


@pytest.fixture(autouse=True)
def _memory_on(monkeypatch: pytest.MonkeyPatch) -> None:
    # These tests exercise the wired path; re-enable memory (suite default is OFF).
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "0")


@pytest.fixture(autouse=True)
def _capability_granted():
    # Gated recall now requires a safety-check capability token (council D3). Every recall in
    # this module exercises the authorized bridge, so hold a grant for the whole module.
    with captoken.granted():
        yield


def _capture(monkeypatch, proc: _Proc):
    calls = {}

    def fake_run(argv, *, input_bytes=None, timeout=45):
        calls["argv"] = argv
        calls["input"] = input_bytes
        return proc

    monkeypatch.setattr(memstore, "_run", fake_run)
    return calls


# --- recall ---------------------------------------------------------------


def test_recall_argv_uses_dr_alex_identity_and_high_ceiling(monkeypatch) -> None:
    payload = json.dumps(
        [
            {
                "id": "m1",
                "type": "user",
                "status": "active",
                "valid_from": "2026-07-01",
                "invalid_at": None,
                "importance": 70,
                "sensitivity": "high",
                "score": 70.0,
                "snippet": "behavioral activation helps mornings",
            }
        ]
    ).encode()
    calls = _capture(monkeypatch, _Proc(0, payload, b""))

    hits = memstore.recall("morning lows", k=5)
    argv = calls["argv"]
    assert "--agent" in argv and argv[argv.index("--agent") + 1] == "dr-alex"
    assert "--client" in argv and argv[argv.index("--client") + 1] == "dr-alex"
    assert (
        "--sensitivity-ceiling" in argv and argv[argv.index("--sensitivity-ceiling") + 1] == "high"
    )
    assert "recall" in argv
    assert "--filter" in argv and "tag=therapy" in argv
    # G14: NO --as-of, so memctl applies status=active + valid-as-of-now by default.
    assert "--as-of" not in argv
    assert len(hits) == 1 and hits[0].id == "m1"
    assert hits[0].sensitivity == "high"


def test_launcher_uses_no_sync_before_the_subcommand(monkeypatch) -> None:
    # D18: `uv run --no-sync` skips per-call resolution WITHOUT touching memctl args/identity.
    calls = _capture(monkeypatch, _Proc(0, b"[]", b""))
    memstore.recall("q", k=1)
    argv = calls["argv"]
    assert argv[:3] == ["uv", "run", "--no-sync"]
    # The flag is uv's own: it appears before the `memctl` subcommand and the identity args.
    assert argv.index("--no-sync") < argv.index("memctl") < argv.index("--client")


def test_recall_degrades_to_empty_on_nonzero_exit(monkeypatch) -> None:
    _capture(monkeypatch, _Proc(10, b"", b"refused"))
    assert memstore.recall("x") == []


def test_recall_degrades_to_empty_on_bad_json(monkeypatch) -> None:
    _capture(monkeypatch, _Proc(0, b"not json", b""))
    assert memstore.recall("x") == []


def test_recall_returns_empty_when_memory_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "1")

    # _run must never even be called when disabled.
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("must not spawn when memory disabled")

    monkeypatch.setattr(memstore, "_run", boom)
    assert memstore.recall("x") == []


# --- remember -------------------------------------------------------------


def test_remember_argv_and_high_sensitivity(monkeypatch) -> None:
    calls = _capture(monkeypatch, _Proc(0, json.dumps({"id": "new-mem"}).encode(), b""))
    res = memstore.remember("A durable fact.", tags=["therapy"], sensitivity="high", importance=70)
    argv = calls["argv"]
    assert res.ok and res.id == "new-mem"
    assert argv[argv.index("--sensitivity") + 1] == "high"
    assert argv[argv.index("--type") + 1] == "user"
    assert "therapy" in argv[argv.index("--tags") + 1]
    assert calls["input"] == b"A durable fact."


def test_remember_passes_idempotency_key(monkeypatch) -> None:
    calls = _capture(monkeypatch, _Proc(0, json.dumps({"id": "same-mem"}).encode(), b""))

    result = memstore.remember("Synthetic fact.", idempotency_key="finalize-v1:abc123")

    argv = calls["argv"]
    assert result.ok and result.id == "same-mem"
    assert argv[argv.index("--idempotency-key") + 1] == "finalize-v1:abc123"


def test_remember_clamps_importance_to_80(monkeypatch) -> None:
    calls = _capture(monkeypatch, _Proc(0, json.dumps({"id": "x"}).encode(), b""))
    memstore.remember("f", importance=99)
    argv = calls["argv"]
    assert argv[argv.index("--importance") + 1] == "80"


def test_remember_reports_failure_without_body(monkeypatch) -> None:
    _capture(monkeypatch, _Proc(4, b'{"status": "quarantined"}', b""))
    res = memstore.remember("f")
    assert res.ok is False
    # Structured reason only — never the body (R3).
    assert res.error == "quarantined"


# --- supersede ------------------------------------------------------------


def test_supersede_argv(monkeypatch) -> None:
    calls = _capture(monkeypatch, _Proc(0, json.dumps({"id": "v2"}).encode(), b""))
    res = memstore.supersede("old-slug", "refined fact", reason="corrected", importance=60)
    argv = calls["argv"]
    assert res.ok and res.id == "v2"
    assert "supersede" in argv and "old-slug" in argv
    assert argv[argv.index("--reason") + 1] == "corrected"


# --- scrub ----------------------------------------------------------------


def test_scrub_returns_clean_bytes(monkeypatch) -> None:
    calls = _capture(monkeypatch, _Proc(0, b"CLEANED", b""))
    out = memstore.scrub_document("some digest")
    assert out == b"CLEANED"
    assert calls["input"] == b"some digest"


def test_scrub_raises_on_failure(monkeypatch) -> None:
    _capture(monkeypatch, _Proc(1, b"", b"boom"))
    with pytest.raises(memstore.ScrubError):
        memstore.scrub_document("x")


def test_inbox_dir_follows_store_root(monkeypatch) -> None:
    monkeypatch.setenv("MEMCTL_ROOT", "/tmp/throwaway-store")
    assert memstore.inbox_dir() == "/tmp/throwaway-store/inbox"
