"""alexd (The Room) — loopback bind, the device gate, /crisis ungated, and the /turn SSE.

The model is faked (there may be no ``claude`` binary / API key here); the SSE plumbing must
still stream, RED must short-circuit before the model, and the empty-output guard must fire.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dr_alex import alexd, llm, pairing
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
            out.append(json.loads(block[len("data:"):].strip()))
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


# ---------------------------------------------------------------------------
# Device-token gate (council D3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("post", "/session/start"),
    ("post", "/turn"),
    ("post", "/session/end"),
    ("post", "/checkin"),
    ("get", "/homework"),
    ("get", "/continuity"),
    ("post", "/export/review"),
])
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
    r = client.post("/turn", json={"session_id": sid, "text": "I had a rough day"}, headers=_auth(token))
    assert r.status_code == 200
    events = _sse_events(r.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    meta = events[0]
    assert meta["tier"] == "GREEN" and meta["crisis"] is False
    # Tokens reconstruct the (gated) reply.
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed == "Let's take this one small step at a time."


def test_red_turn_streams_only_the_crisis_card_and_never_calls_the_model(client, monkeypatch) -> None:
    def boom(*a, **k):  # the model must NOT run on a RED turn
        raise AssertionError("model must not run on RED")
    monkeypatch.setattr(llm, "generate", boom)
    token = _pair(client)
    sid = client.post("/session/start", json={}, headers=_auth(token)).json()["session_id"]
    r = client.post("/turn", json={"session_id": sid, "text": "I want to kill myself"}, headers=_auth(token))
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
    r = client.post("/turn", json={"session_id": sid, "text": "just checking in"}, headers=_auth(token))
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
    r1 = client.post("/turn", json={"session_id": sid, "text": "I keep", "fragment": True}, headers=_auth(token))
    assert _sse_events(r1.text)[0]["type"] == "buffered"
    assert seen["text"] is None
    # The final message flushes the buffer + coalesces.
    r2 = client.post("/turn", json={"session_id": sid, "text": "circling the same worry"}, headers=_auth(token))
    assert _sse_events(r2.text)[-1]["type"] == "done"
    assert seen["text"] == "I keep\ncircling the same worry"


def test_export_review_generates_a_real_export(client) -> None:
    token = _pair(client)
    r = client.post("/export/review", json={"from": "2026-07-01", "to": "2026-07-18"},
                    headers=_auth(token))
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
