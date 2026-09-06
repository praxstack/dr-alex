"""alexd (The Room) — loopback bind, the device gate, /crisis ungated, and the /turn SSE.

The model is faked (there may be no ``claude`` binary / API key here); the SSE plumbing must
still stream, RED must short-circuit before the model, and the empty-output guard must fire.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dr_alex import alexd, llm, pairing, statedb
from safety.triage import Tier


@pytest.fixture()
def client(monkeypatch):
    alexd._sessions.clear()
    return TestClient(alexd.app)


def _pair(client) -> str:
    code = pairing.create_pairing_code()
    resp = client.post("/pair", json={"code": code, "label": "test-phone"})
    assert resp.status_code == 200, resp.text
    return resp.json()["device_token"]


def _auth(token: str) -> dict:
    return {alexd.DEVICE_HEADER: token}


def _fake_llm(text: str):
    def _gen(messages, tier, **kwargs):
        return llm.LLMResult(ok=True, text=text, tier=tier)

    return _gen


def _sse_events(body: str) -> list[dict]:
    out = []
    for block in body.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            out.append(json.loads(block[len("data:") :].strip()))
    return out


# ---------------------------------------------------------------------------
# Loopback hard-assert (council D3 rider 1)
# ---------------------------------------------------------------------------


def test_loopback_bind_is_enforced() -> None:
    assert alexd.require_loopback("127.0.0.1") == "127.0.0.1"
    assert alexd.require_loopback("localhost") == "localhost"
    for banned in ("0.0.0.0", "192.168.1.5", "10.0.0.2", "::", "example.ts.net"):
        with pytest.raises(alexd.NonLoopbackBindRefused):
            alexd.require_loopback(banned)


def test_cli_default_port_leaves_cursor_oauth_port_free(monkeypatch) -> None:
    from dr_alex import cli

    bound = {}
    monkeypatch.setattr(alexd, "serve", lambda **kwargs: bound.update(kwargs))
    assert cli._serve_command([]) == 0
    assert bound == {"host": "127.0.0.1", "port": 18787}


def test_serve_refuses_non_loopback_without_binding(monkeypatch) -> None:
    called = {"run": False}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: called.__setitem__("run", True))
    with pytest.raises(alexd.NonLoopbackBindRefused):
        alexd.serve(host="0.0.0.0")
    assert called["run"] is False  # never reached uvicorn.run


# ---------------------------------------------------------------------------
# /healthz + /crisis — ungated
# ---------------------------------------------------------------------------


def test_healthz_is_ungated(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["loopback"] is True


def test_crisis_is_ungated_static_and_carries_no_personal_data(client) -> None:
    r = client.get("/crisis")  # NO device token
    assert r.status_code == 200
    body = r.text
    # Crisis resources present (hard-coded, model-free)…
    assert "14416" in body
    assert "Shreya" in body
    for num in ("9152987821", "9820466726", "1860-2662-345", "112"):
        assert num in body
    # …zero personal data / session state.
    for leak in ("Ria", "Shahjahanpur", "session_id", "continuity", "PERSONAL_MEMORY"):
        assert leak not in body


def test_app_shell_and_assets_are_ungated(client) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/manifest.json").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/sw.js").status_code == 200
    # The service worker must be allowed the whole-origin scope.
    assert client.get("/sw.js").headers.get("Service-Worker-Allowed") == "/"


def test_shell_and_assets_carry_hardening_headers(client) -> None:
    # D19: the shell + every asset (+ the crisis card) carry a strict self-only CSP and the
    # standard response-hardening headers. The PWA is self-contained so nothing external breaks.
    for path in ("/", "/crisis", "/manifest.json", "/app.css", "/app.js", "/sw.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp, path
        assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp, path
        assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0], (
            path
        )
        assert r.headers.get("X-Content-Type-Options") == "nosniff", path
        assert r.headers.get("Referrer-Policy") == "no-referrer", path
    # The PWA still loads: the shell references only same-origin assets, all present.
    assert '<script src="/app.js"' in client.get("/").text


# ---------------------------------------------------------------------------
# Device-token gate (council D3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/session/start"),
        ("post", "/turn"),
        ("post", "/session/end"),
        ("post", "/checkin"),
        ("get", "/homework"),
        ("get", "/continuity"),
        ("post", "/export/review"),
    ],
)
def test_endpoints_require_device_token(client, method, path) -> None:
    resp = client.post(path, json={}) if method == "post" else client.get(path)
    assert resp.status_code == 401


def test_bad_device_token_is_rejected(client) -> None:
    r = client.get("/homework", headers=_auth("bogus-token"))
    assert r.status_code == 401


def test_pairing_then_gated_access(client) -> None:
    token = _pair(client)
    r = client.get("/homework", headers=_auth(token))
    assert r.status_code == 200
    assert "homework" in r.json()


def test_pair_rejects_bad_code(client) -> None:
    r = client.post("/pair", json={"code": "NOPENOPE"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Session + the turn (SSE)
# ---------------------------------------------------------------------------


def test_session_start_returns_greeting(client) -> None:
    token = _pair(client)
    r = client.post("/session/start", json={"mood": 5}, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["greeting"]
    assert r.json()["session_id"]


def test_benign_turn_streams_tokens(client, monkeypatch) -> None:
    monkeypatch.setattr(llm, "generate", _fake_llm("Let's take this one small step at a time."))
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r = client.post(
        "/turn", json={"session_id": sid, "text": "I had a rough day"}, headers=_auth(token)
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    meta = events[0]
    assert meta["tier"] == "GREEN" and meta["crisis"] is False
    # Tokens reconstruct the (gated) reply.
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed == "Let's take this one small step at a time."


def test_red_turn_streams_only_the_crisis_card_and_never_calls_the_model(
    client, monkeypatch
) -> None:
    def boom(*a, **k):  # the model must NOT run on a RED turn
        raise AssertionError("model must not run on RED")

    monkeypatch.setattr(llm, "generate", boom)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r = client.post(
        "/turn", json={"session_id": sid, "text": "I want to kill myself"}, headers=_auth(token)
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert events[0]["type"] == "meta" and events[0]["crisis"] is True
    assert events[0]["tier"] == "RED"
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert "14416" in streamed and "Shreya" in streamed


def test_empty_reply_is_guarded_before_streaming(client, monkeypatch) -> None:
    monkeypatch.setattr(llm, "generate", _fake_llm(""))  # model returns nothing
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r = client.post(
        "/turn", json={"session_id": sid, "text": "just checking in"}, headers=_auth(token)
    )
    streamed = "".join(e["text"] for e in _sse_events(r.text) if e["type"] == "token")
    from dr_alex import wire

    assert streamed == wire.EMPTY_REPLY_FALLBACK  # never an empty reply


def test_turn_fragment_is_buffered_then_coalesced(client, monkeypatch) -> None:
    seen = {"text": None}

    def _gen(messages, tier, **kwargs):
        seen["text"] = messages[-1].content
        return llm.LLMResult(ok=True, text="okay.", tier=tier)

    monkeypatch.setattr(llm, "generate", _gen)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    # A non-final fragment is buffered (no model call, just an ack).
    r1 = client.post(
        "/turn", json={"session_id": sid, "text": "I keep", "fragment": True}, headers=_auth(token)
    )
    assert _sse_events(r1.text)[0]["type"] == "buffered"
    assert seen["text"] is None
    # The final message flushes the buffer + coalesces.
    r2 = client.post(
        "/turn", json={"session_id": sid, "text": "circling the same worry"}, headers=_auth(token)
    )
    assert _sse_events(r2.text)[-1]["type"] == "done"
    assert seen["text"] == "I keep\ncircling the same worry"


def test_timer_flushed_fragment_is_not_dropped(client, monkeypatch) -> None:
    # D10: if the debounce window times out before the final message arrives, the buffered
    # fragment must survive (via the session's pending buffer), not vanish into a no-op.
    seen = {"text": None}

    def _gen(messages, tier, **kwargs):
        seen["text"] = messages[-1].content
        return llm.LLMResult(ok=True, text="okay.", tier=tier)

    monkeypatch.setattr(llm, "generate", _gen)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r1 = client.post(
        "/turn", json={"session_id": sid, "text": "I keep", "fragment": True}, headers=_auth(token)
    )
    assert _sse_events(r1.text)[0]["type"] == "buffered"
    # Simulate the 4s debounce window elapsing (timer flush) BEFORE the final fragment.
    alexd._sessions[sid].debounce._on_timer(sid)
    assert seen["text"] is None  # not delivered yet, but retained
    # The next message folds the timer-flushed fragment back in — nothing lost.
    r2 = client.post(
        "/turn", json={"session_id": sid, "text": "circling the same worry"}, headers=_auth(token)
    )
    assert _sse_events(r2.text)[-1]["type"] == "done"
    assert seen["text"] == "I keep\ncircling the same worry"


def test_pending_coalesced_text_survives_finalize(client, monkeypatch) -> None:
    # D10: if a session finalizes (/session/end) with timer/cap-flushed fragments still
    # pending and no subsequent /turn, that text must NOT be silently dropped — it is drained
    # into one final considered turn before the session is discarded.
    seen = {"text": None}

    def _gen(messages, tier, **kwargs):
        seen["text"] = messages[-1].content
        return llm.LLMResult(ok=True, text="okay.", tier=tier)

    monkeypatch.setattr(llm, "generate", _gen)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r1 = client.post(
        "/turn",
        json={"session_id": sid, "text": "I never told anyone this", "fragment": True},
        headers=_auth(token),
    )
    assert _sse_events(r1.text)[0]["type"] == "buffered"
    # The debounce window elapses (timer flush) — the fragment is parked in the pending buffer.
    alexd._sessions[sid].debounce._on_timer(sid)
    assert seen["text"] is None  # nothing processed yet, but retained
    # Ending the session drains the pending text into one final considered turn — nothing lost.
    r2 = client.post("/session/end", json={"session_id": sid}, headers=_auth(token))
    assert r2.status_code == 200
    assert seen["text"] == "I never told anyone this"  # the parked thought reached a turn
    assert sid not in alexd._sessions  # session finalized and cleaned up


def test_crisis_fragment_bypasses_debounce_and_fires_immediately(client, monkeypatch) -> None:
    """D6: a RED fragment must NEVER wait in the debounce buffer — it bypasses via the real
    crisis_prescreen wiring and streams the crisis card immediately, with no model call."""

    def boom(*a, **k):  # the model must NOT run on a RED turn
        raise AssertionError("model must not run on a RED crisis fragment")

    monkeypatch.setattr(llm, "generate", boom)

    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]

    # fragment=True would normally buffer — but a crisis fragment bypasses the debounce.
    r = client.post(
        "/turn",
        json={"session_id": sid, "text": "I want to kill myself", "fragment": True},
        headers=_auth(token),
    )
    assert r.status_code == 200
    events = _sse_events(r.text)
    kinds = [e["type"] for e in events]
    # It fired the crisis path immediately — NOT buffered.
    assert "buffered" not in kinds
    assert events[0]["type"] == "meta"
    assert events[0]["crisis"] is True and events[0]["tier"] == "RED"
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert "14416" in streamed and "Shreya" in streamed
    # Nothing was left buffered for this session.
    assert alexd._sessions[sid].debounce.pending_count() == 0


def test_export_review_generates_a_real_export(client) -> None:
    token = _pair(client)
    r = client.post(
        "/export/review", json={"from": "2026-07-01", "to": "2026-07-18"}, headers=_auth(token)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["range"] == {"from": "2026-07-01", "to": "2026-07-18"}
    # Real files were written locally; only date-only paths cross the wire (no clinical content).
    assert body["markdown_path"] and body["markdown_path"].endswith(".md")
    assert body["html_path"] and body["html_path"].endswith(".html")
    import os

    assert os.path.exists(body["html_path"])


def test_run_turn_outcome_carries_structural_provenance(monkeypatch) -> None:
    from dr_alex import engine

    monkeypatch.setattr(llm, "generate", _fake_llm("a calm reply"))
    out = engine.run_turn("I had a hard day", memory_ids=["01JMEM"])
    assert isinstance(out, engine.TurnOutcome)
    assert out.tier in (Tier.GREEN, Tier.AMBER)
    assert out.memory_ids == ["01JMEM"]
    assert isinstance(out.chunk_ids, list)


def test_request_retry_replays_completed_reply_and_rejects_payload_conflict(
    client, monkeypatch
) -> None:
    calls = {"count": 0}

    def _gen(messages, tier, **kwargs):
        calls["count"] += 1
        return llm.LLMResult(ok=True, text="one durable reply", tier=tier)

    monkeypatch.setattr(llm, "generate", _gen)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    payload = {"session_id": sid, "text": "same request", "request_id": "request-1"}
    first = _sse_events(client.post("/turn", json=payload, headers=_auth(token)).text)
    second = _sse_events(client.post("/turn", json=payload, headers=_auth(token)).text)
    assert calls["count"] == 1
    assert "one durable reply" == "".join(e.get("text", "") for e in second if e["type"] == "token")
    assert any(e.get("replayed") for e in second if e["type"] == "meta")
    assert (
        client.post("/turn", json={**payload, "text": "changed"}, headers=_auth(token)).status_code
        == 409
    )
    assert len(statedb.load_transcript(sid)) == 2
    assert first[-1]["durable"] is True and second[-1]["durable"] is True


def test_restart_restores_transcript_but_red_is_excluded_from_model_history(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(llm, "generate", _fake_llm("green reply"))
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    client.post(
        "/turn",
        json={"session_id": sid, "text": "ordinary", "request_id": "green-1"},
        headers=_auth(token),
    )
    client.post(
        "/turn",
        json={"session_id": sid, "text": "I want to kill myself", "request_id": "red-1"},
        headers=_auth(token),
    )
    alexd._sessions.clear()
    restored = client.post("/session/start", json={"session_id": sid}, headers=_auth(token)).json()
    texts = [r["text"] for r in restored["transcript"]]
    assert texts[:3] == ["ordinary", "green reply", "I want to kill myself"]
    assert "14416" in texts[3]
    resumed = alexd._sessions[sid]
    assert all("I want to kill myself" not in m.content for m in resumed.history)


def test_session_end_calls_fanout_and_recovery_is_reachable(client, monkeypatch) -> None:
    from dr_alex import fanout

    calls = {"end": 0, "recover": 0}
    monkeypatch.setattr(alexd.memstore, "memory_enabled", lambda: True)
    monkeypatch.setattr(
        fanout, "recover_if_needed", lambda: calls.__setitem__("recover", calls["recover"] + 1)
    )
    monkeypatch.setattr(
        fanout,
        "finalize_session",
        lambda *a, **k: calls.__setitem__("end", calls["end"] + 1) or None,
    )
    monkeypatch.setattr(llm, "generate", _fake_llm("reply"))
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    client.post(
        "/turn",
        json={"session_id": sid, "text": "hello", "request_id": "fanout-1"},
        headers=_auth(token),
    )
    client.post("/session/end", json={"session_id": sid}, headers=_auth(token))
    assert calls == {"end": 1, "recover": 1}


def test_storage_failure_is_reported_without_blocking_crisis_response(client, monkeypatch) -> None:
    monkeypatch.setattr(statedb, "record_api_event", lambda *a, **k: "failed")
    monkeypatch.setattr(statedb, "begin_turn_request", lambda *a, **k: None)
    monkeypatch.setattr(
        llm,
        "generate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("RED must stay model-free")),
    )
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    events = _sse_events(
        client.post(
            "/turn",
            json={"session_id": sid, "text": "I want to kill myself", "request_id": "red-storage"},
            headers=_auth(token),
        ).text
    )
    assert "14416" in "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert events[0]["durable"] is False and events[-1]["durable"] is False


def test_retry_after_generation_failure_reuses_assembled_fragment_input(
    client, monkeypatch
) -> None:
    """A pending request retry must not lose the fragment drained by its first attempt."""
    seen: list[str] = []
    calls = {"n": 0}

    def generate(messages, tier, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient model failure")
        seen.append(messages[-1].content)
        return llm.LLMResult(ok=True, text="recovered", tier=tier)

    monkeypatch.setattr(llm, "generate", generate)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    fragment = {
        "session_id": sid,
        "text": "the first part",
        "fragment": True,
        "request_id": "frag-retry",
    }
    assert _sse_events(client.post("/turn", json=fragment, headers=_auth(token)).text)[0]["durable"]
    payload = {"session_id": sid, "text": "the final part", "request_id": "turn-retry"}
    with pytest.raises(RuntimeError):
        client.post("/turn", json=payload, headers=_auth(token))
    retry = client.post("/turn", json=payload, headers=_auth(token))
    assert retry.status_code == 200
    assert calls["n"] == 2
    assert seen == ["the first part\nthe final part"]


def test_restart_restores_durable_raw_fragment_for_next_turn(client, monkeypatch) -> None:
    seen: list[str] = []

    def generate(messages, tier, **kwargs):
        seen.append(messages[-1].content)
        return llm.LLMResult(ok=True, text="restored", tier=tier)

    monkeypatch.setattr(llm, "generate", generate)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r = client.post(
        "/turn",
        json={
            "session_id": sid,
            "text": "durable earlier thought",
            "fragment": True,
            "request_id": "raw-1",
        },
        headers=_auth(token),
    )
    assert _sse_events(r.text)[0]["durable"] is True
    alexd._sessions.clear()  # simulate a process restart; state.db remains
    client.post("/session/start", json={"session_id": sid}, headers=_auth(token))
    client.post(
        "/turn",
        json={"session_id": sid, "text": "and the conclusion", "request_id": "raw-turn"},
        headers=_auth(token),
    )
    assert seen == ["durable earlier thought\nand the conclusion"]


def test_telemetry_off_fragment_is_not_false_durable_ack(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_TELEMETRY_OFF", "1")
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    response = client.post(
        "/turn",
        json={"session_id": sid, "text": "ordinary fragment", "fragment": True},
        headers=_auth(token),
    )
    assert response.status_code == 503
    assert response.json()["durable"] is False


def test_safety_flags_commit_with_completed_reply(client, monkeypatch) -> None:
    monkeypatch.setattr(
        llm,
        "generate",
        _fake_llm("I hear you. Are you having thoughts of hurting yourself right now?"),
    )
    monkeypatch.setattr(
        statedb,
        "update_session_state",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("completion must own the safety-state transaction")
        ),
    )
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    response = client.post(
        "/turn",
        json={"session_id": sid, "text": "I feel hopeless and worthless", "request_id": "flags-1"},
        headers=_auth(token),
    )
    events = _sse_events(response.text)
    assert events[0]["durable"] is True
    alexd._sessions.clear()
    client.post("/session/start", json={"session_id": sid}, headers=_auth(token))
    assert alexd._sessions[sid].state.safety_probe_asked is True


def test_session_end_filters_red_rows_before_memory_fanout(client, monkeypatch) -> None:
    from dr_alex import fanout

    captured = {}
    monkeypatch.setattr(alexd.memstore, "memory_enabled", lambda: True)
    monkeypatch.setattr(fanout, "should_finalize", lambda *a, **k: True)
    monkeypatch.setattr(
        fanout,
        "finalize_session",
        lambda turns, **kwargs: captured.update(turns=turns, risk=kwargs["risk_tier_max"]) or None,
    )
    monkeypatch.setattr(llm, "generate", _fake_llm("safe reply"))
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    client.post(
        "/turn",
        json={"session_id": sid, "text": "I want to kill myself", "request_id": "fan-red"},
        headers=_auth(token),
    )
    client.post(
        "/turn",
        json={"session_id": sid, "text": "I had breakfast", "request_id": "fan-green"},
        headers=_auth(token),
    )
    client.post("/session/end", json={"session_id": sid}, headers=_auth(token))
    assert all("kill myself" not in text for _role, text in captured["turns"])
    assert captured["risk"] == "RED"  # RED withholding survives the body filter


def test_failed_final_storage_retries_without_duplicate_final_text(client, monkeypatch) -> None:
    seen: list[str] = []
    original_record = statedb.record_api_event
    failed_once = {"value": False}

    def record_event(request_id, **kwargs):
        if kwargs.get("event_type") == "turn" and not failed_once["value"]:
            failed_once["value"] = True
            return "failed"
        return original_record(request_id, **kwargs)

    monkeypatch.setattr(statedb, "record_api_event", record_event)
    monkeypatch.setattr(
        llm,
        "generate",
        lambda messages, tier, **kwargs: (
            seen.append(messages[-1].content) or llm.LLMResult(ok=True, text="once", tier=tier)
        ),
    )
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    client.post(
        "/turn",
        json={"session_id": sid, "text": "earlier", "fragment": True, "request_id": "park-1"},
        headers=_auth(token),
    )
    payload = {"session_id": sid, "text": "only once", "request_id": "park-turn"}
    assert client.post("/turn", json=payload, headers=_auth(token)).status_code == 503
    assert client.post("/turn", json=payload, headers=_auth(token)).status_code == 200
    assert seen == ["earlier\nonly once"]


def test_readiness_requires_recent_successful_model_probe(client, monkeypatch):
    monkeypatch.setattr(
        llm,
        "model_status",
        lambda: {
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "transport_available": True,
            "ok": None,
            "checked_at": None,
        },
    )
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert client.post("/model/probe").status_code == 401
    token = _pair(client)
    observed = {}

    def complete(triage, messages, **kwargs):
        observed.update(kwargs)
        assert len(messages) == 1 and "synthetic" in messages[0].content
        return llm.LLMResult(ok=True, text="READY", tier=triage.tier)

    monkeypatch.setattr(llm, "complete", complete)
    assert client.post("/model/probe", headers=_auth(token)).status_code == 200
    assert "personal context" in observed["system_prompt"]
    import time

    monkeypatch.setattr(
        llm,
        "model_status",
        lambda: {"transport_available": True, "ok": True, "checked_at": time.time()},
    )
    assert client.get("/readyz").status_code == 200
