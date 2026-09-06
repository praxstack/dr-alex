"""Hermes transport onto the same paired, triaged and durable Dr. Alex engine.

Provider instructions/tools never replace the local persona or safety policy. Only
native Hermes session identity is accepted; a guessed identity could mix conversations.
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from dr_alex import pairing, statedb, wire

_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.:-]{0,159}\Z")
_MAX_BODY = 2_000_000


def _text(content: object) -> str:
    if isinstance(content, list):
        if not all(
            isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)
            for p in content
        ):
            raise HTTPException(422, "only text input is supported")
        content = "\n".join(p["text"] for p in content)
    if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
        raise HTTPException(422, "nonempty text of at most 100000 characters is required")
    return content


async def _authorized(request: Request) -> None:
    token = request.headers.get("authorization", "")
    if not token.startswith("Bearer ") or not pairing.verify_device_token(token[7:]):
        raise HTTPException(401, "device not paired")


def register(app: FastAPI) -> None:
    @app.get("/v1/models")
    async def models(request: Request):
        await _authorized(request)
        return {
            "object": "list",
            "data": [{"id": "dr-alex", "object": "model", "owned_by": "local"}],
        }

    @app.post("/v1/chat/completions")
    async def completion(request: Request):
        from dr_alex import alexd  # factory is complete before a request reaches this route

        await _authorized(request)
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > _MAX_BODY:
                raise HTTPException(413, "request too large")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(422, "invalid JSON") from None
        if not isinstance(payload, dict):
            raise HTTPException(422, "request object required")
        sid = request.headers.get("X-Hermes-Session-Id") or payload.get("session_id")
        if not isinstance(sid, str) or not _ID.fullmatch(sid):
            raise HTTPException(422, "native Hermes session_id required")
        if payload.get("model") not in ("dr-alex", "hermes-agent"):
            raise HTTPException(422, "model must be dr-alex")
        messages = payload.get("messages")
        if (
            not isinstance(messages, list)
            or not messages
            or not all(isinstance(m, dict) for m in messages)
            or messages[-1].get("role") != "user"
        ):
            raise HTTPException(422, "messages must end with a user turn")
        text = _text(messages[-1].get("content"))
        # Stable across SDK retries. Include prior turns to distinguish repeated
        # identical words later in the same conversation; ignore mutable system prompts.
        conversation = [m for m in messages if m.get("role") in ("user", "assistant")]
        digest = hashlib.sha256(
            json.dumps(conversation, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        session_id = "hermes-" + sid
        explicit_id = request.headers.get("Idempotency-Key")
        if explicit_id is not None and not _ID.fullmatch(explicit_id):
            raise HTTPException(422, "invalid idempotency key")
        request_id = hashlib.sha256(f"{session_id}:{explicit_id or digest}".encode()).hexdigest()
        sess = alexd._get_or_create_session(session_id)
        if not statedb.start_session(session_id, is_test_traffic=sess.test_traffic):
            raise HTTPException(503, "conversation storage unavailable; retry this turn")
        try:
            out = await run_in_threadpool(
                alexd._run_turn_blocking,
                sess,
                text,
                request_id=request_id,
                request_payload_hash=digest,
            )
        except statedb.RequestPayloadConflict:
            raise HTTPException(409, "idempotency key reused with different input") from None
        except Exception:
            raise HTTPException(503, "turn could not complete; retry this turn") from None
        if not out.durable:
            raise HTTPException(503, "conversation storage unavailable; retry this turn")
        answer, guarded = wire.empty_output_guard(out.text)
        wire.audit_turn(
            tier=out.tier,
            safety_path_taken=out.safety_action,
            chunk_ids=out.chunk_ids,
            memory_ids=out.memory_ids,
            empty_guarded=guarded,
        )
        common = {"id": "chatcmpl-" + request_id, "created": int(time.time()), "model": "dr-alex"}
        if payload.get("stream"):
            chunk = {
                **common,
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": answer},
                        "finish_reason": None,
                    }
                ],
            }
            stop = {
                **common,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            return StreamingResponse(
                iter(
                    [
                        "data: " + json.dumps(chunk) + "\n\n",
                        "data: " + json.dumps(stop) + "\n\n",
                        "data: [DONE]\n\n",
                    ]
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            {
                **common,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": answer},
                        "finish_reason": "stop",
                    }
                ],
            },
            headers={"Cache-Control": "no-store"},
        )
