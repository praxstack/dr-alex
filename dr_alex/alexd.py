"""``alexd`` — the local FastAPI front door onto the Dr. Alex spine (Phase 5, "The Room").

This is a NEW front door, not a new brain. Every turn routes through the SAME single engine
function the TUI uses (:func:`dr_alex.engine.run_turn`), so triage STEP 0 runs first in code,
RED short-circuits before retrieval and before the model, and the deterministic output gates
run before a token reaches the phone (Directive 1). ``alexd`` adds only the transport: an SSE
turn stream, a device-pairing gate, the G16 wire-decision audit + empty-output guard, and the
G17 debounce.

Hard invariants enforced here:
  * **Loopback only (council D3 rider 1).** The service refuses to start on anything but a
    loopback host. 0.0.0.0 / LAN / any tunnel is banned — reach the phone via ``tailscale
    serve`` (see ``tools/tailscale-setup.sh``), never by widening this bind.
  * **Device-token gate (D3).** Every endpoint except ``/crisis``, ``/healthz``, ``/pair`` and
    the static app shell requires a valid device token.
  * **/crisis is static, model-free, ungated** and renders offline from the PWA precache.
  * **R3 hygiene.** All message content travels in POST bodies, never in URLs/query strings;
    logs carry structured facts only.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from dr_alex import (
    continuity as _continuity,
    debounce as _debounce,
    engine,
    llm,
    memstore,
    pairing,
    statedb,
    telemetry,
    wire,
)
from dr_alex.session import SessionState
from safety import crisis_card, crisis_prescreen
from safety.triage import Tier

_log = logging.getLogger("dr_alex.alexd")

HOST = "127.0.0.1"
PORT = 8787
ROOM_DIR = Path(__file__).resolve().parent / "room"

#: The only hosts alexd will ever bind. 0.0.0.0 / LAN / a tunnel address is refused (D3 r1).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class NonLoopbackBindRefused(RuntimeError):
    """alexd was asked to bind a non-loopback host — refused (council D3 rider 1)."""


def require_loopback(host: str) -> str:
    """Return ``host`` iff it is a loopback address; else raise. The hard bind guard (D3 r1).

    Banned by construction: ``0.0.0.0``, any LAN IP, any tunnel/ngrok/cloudflared address.
    The phone reaches alexd through ``tailscale serve`` terminating locally at 127.0.0.1 — the
    bind itself never widens.
    """
    h = (host or "").strip()
    if h not in LOOPBACK_HOSTS:
        raise NonLoopbackBindRefused(
            f"alexd binds loopback only (one of {sorted(LOOPBACK_HOSTS)}); refusing host {host!r}. "
            "Reach the phone via `tailscale serve https / 127.0.0.1:8787`, never by binding "
            "0.0.0.0/LAN/a tunnel (council D3 rider 1)."
        )
    return h


# ---------------------------------------------------------------------------
# In-process session registry (high-churn state; never the durable store).
# ---------------------------------------------------------------------------


class RoomSession:
    """One PWA conversation — mirrors the TUI's per-session bookkeeping (in memory)."""

    def __init__(self, session_id: str, *, test_traffic: bool) -> None:
        self.session_id = session_id
        self.state = SessionState()
        self.history: list[llm.Message] = []
        self.system_prompt = engine.system_prompt()
        self.memory_ids: list[str] = []
        self.started_at = _iso_now()
        self.test_traffic = test_traffic
        self.mood_phase = "open"
        self.debounce = _debounce.DebounceBuffer(flush_callback=lambda _p: None)

    def assemble_memory(self) -> None:
        """Best-effort session-start memory (G20). Degrades to the base prompt on any error."""
        if not memstore.memory_enabled():
            return
        try:
            mem = engine.assemble_startup_memory()
            self.system_prompt = engine.system_prompt_with_memory(mem)
            self.memory_ids = list(mem.recalled_ids)
        except Exception:  # noqa: BLE001 — a broken store must never break session start
            pass


_sessions: dict[str, RoomSession] = {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_session_id() -> str:
    return _iso_now().replace(":", "").replace("-", "")


def _get_or_create_session(session_id: str | None) -> RoomSession:
    sid = session_id or _new_session_id()
    sess = _sessions.get(sid)
    if sess is None:
        sess = RoomSession(sid, test_traffic=telemetry.is_test_traffic())
        _sessions[sid] = sess
    return sess


# ---------------------------------------------------------------------------
# Device-token gate (council D3) — everything but /crisis, /healthz, /pair, the shell.
# ---------------------------------------------------------------------------

DEVICE_HEADER = "X-Dr-Alex-Device-Token"


async def require_device(
    x_dr_alex_device_token: str | None = Header(default=None, alias=DEVICE_HEADER),
) -> str:
    """FastAPI dependency: 401 unless a valid, non-revoked device token is presented."""
    if not pairing.verify_device_token(x_dr_alex_device_token):
        raise HTTPException(status_code=401, detail="device not paired")
    return x_dr_alex_device_token  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _run_turn_blocking(sess: RoomSession, text: str) -> engine.TurnOutcome:
    """Run the SINGLE turn function on a worker thread (it may spawn the model subprocess)."""
    out = engine.run_turn(
        text,
        history=list(sess.history),
        session=sess.state,
        session_id=sess.session_id,
        system_prompt_override=sess.system_prompt,
        memory_ids=sess.memory_ids,
    )
    # Maintain conversation history for GREEN/AMBER turns (RED is not a conversational turn).
    if out.tier is not Tier.RED:
        sess.history.append(llm.Message(role="user", content=text))
        sess.history.append(llm.Message(role="assistant", content=out.text))
    return out


# ---------------------------------------------------------------------------
# Static asset serving (the PWA shell — ungated, self-contained, offline-cacheable)
# ---------------------------------------------------------------------------


def _read_room(name: str) -> str | None:
    p = (ROOM_DIR / name).resolve()
    # containment: never serve outside ROOM_DIR
    if ROOM_DIR not in p.parents and p != ROOM_DIR:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _asset_response(name: str) -> Response:
    body = _read_room(name)
    if body is None:
        raise HTTPException(status_code=404, detail="not found")
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if name.endswith(".js"):
        ctype = "text/javascript"
    headers = {}
    # The service worker must be allowed to control the whole origin scope.
    if name == "sw.js":
        headers["Service-Worker-Allowed"] = "/"
    return Response(content=body, media_type=ctype, headers=headers)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="alexd", docs_url=None, redoc_url=None, openapi_url=None)

    # -- ungated: static shell + manifest + service worker ----------------

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        body = _read_room("index.html")
        if body is None:  # pragma: no cover - room assets are shipped with the package
            raise HTTPException(status_code=500, detail="app shell missing")
        return HTMLResponse(content=body)

    @app.get("/manifest.json")
    async def manifest() -> Response:
        return _asset_response("manifest.json")

    @app.get("/sw.js")
    async def service_worker() -> Response:
        return _asset_response("sw.js")

    @app.get("/app.css")
    async def app_css() -> Response:
        return _asset_response("app.css")

    @app.get("/app.js")
    async def app_js() -> Response:
        return _asset_response("app.js")

    # -- ungated: crisis (STATIC, model-free) -----------------------------

    @app.get("/crisis", response_class=HTMLResponse)
    async def crisis() -> HTMLResponse:
        """The offline-capable crisis card. No model, no session, no personal data (D3 r4).

        Served from a static, precached page so it renders with the Mac asleep / off-network.
        """
        body = _read_room("crisis.html")
        if body is None:  # pragma: no cover
            # Fall back to a rendered card from the single source of truth (still model-free).
            body = "<pre>" + crisis_card.render_text() + "</pre>"
        return HTMLResponse(content=body)

    # -- ungated: health --------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "service": "alexd", "loopback": True})

    # -- ungated (pairing-code protected): device pairing exchange --------

    @app.post("/pair")
    async def pair(request: Request) -> JSONResponse:
        """Exchange a one-time pairing code (from ``dr-alex pair``) for a device token.

        Ungated by design (you can't have a token yet) but protected by the pairing code
        itself: single-use, TTL ≤ 5min, rate-limited (lockout after 5 fails), constant-time.
        """
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        code = str(payload.get("code", "")) if isinstance(payload, dict) else ""
        label = str(payload.get("label", "")) if isinstance(payload, dict) else ""
        try:
            dev = pairing.redeem_pairing_code(code, label=label or None)
        except pairing.PairingLockedOut:
            raise HTTPException(status_code=429, detail="too many attempts; try again later")
        if dev is None:
            raise HTTPException(status_code=401, detail="invalid or expired pairing code")
        return JSONResponse({"device_id": dev.id, "device_token": dev.token})

    # -- gated: session lifecycle -----------------------------------------

    @app.post("/session/start", dependencies=[Depends(require_device)])
    async def session_start(request: Request) -> JSONResponse:
        payload = await _json(request)
        sess = _get_or_create_session(payload.get("session_id"))
        try:
            statedb.start_session(sess.session_id, is_test_traffic=sess.test_traffic)
        except Exception:  # noqa: BLE001 — telemetry never blocks a session
            pass
        # Optional arriving mood chip (1–10).
        mood = _as_mood(payload.get("mood"))
        if mood is not None:
            _record_mood(sess, "open", mood)
        # Session-start memory context (G20), off the request's hot path is not needed here —
        # it's a one-time assemble and degrades safely.
        await run_in_threadpool(sess.assemble_memory)
        ack = None
        try:
            ack = telemetry.take_repair_ack()
        except Exception:  # noqa: BLE001
            ack = None
        return JSONResponse({
            "session_id": sess.session_id,
            "greeting": engine.greeting(),
            "repair_ack": ack,
        })

    @app.post("/session/end", dependencies=[Depends(require_device)])
    async def session_end(request: Request) -> JSONResponse:
        payload = await _json(request)
        sid = payload.get("session_id")
        sess = _sessions.get(sid) if sid else None
        mood = _as_mood(payload.get("mood"))
        if sess is not None and mood is not None:
            _record_mood(sess, "close", mood)
        if sid:
            try:
                statedb.end_session(sid)
            except Exception:  # noqa: BLE001
                pass
            _sessions.pop(sid, None)
        return JSONResponse({"ok": True})

    # -- gated: the turn (SSE) --------------------------------------------

    @app.post("/turn", dependencies=[Depends(require_device)])
    async def turn(request: Request):
        payload = await _json(request)
        sess = _get_or_create_session(payload.get("session_id"))
        text = str(payload.get("text", "") or "")
        is_fragment = bool(payload.get("fragment", False))

        # G17 debounce + crisis prescreen bypass. A crisis fragment NEVER waits on the window.
        bypass, _reason = crisis_prescreen.should_bypass_debounce(text)
        if is_fragment and not bypass:
            sess.debounce.push(sess.session_id, text)
            async def _buffered():
                yield _sse({"type": "buffered", "pending": sess.debounce.pending_count()})
            return StreamingResponse(_buffered(), media_type="text/event-stream")

        # Final fragment (or a lone message, or a crisis bypass): coalesce any buffered
        # fragments for this session, then run ONE considered turn on the joined text.
        buffered = sess.debounce.flush_now(sess.session_id)
        coalesced = f"{buffered.text}\n{text}".strip() if buffered and buffered.text else text

        if not coalesced.strip():
            async def _empty():
                yield _sse({"type": "done", "tier": "GREEN"})
            return StreamingResponse(_empty(), media_type="text/event-stream")

        async def _stream():
            out = await run_in_threadpool(_run_turn_blocking, sess, coalesced)
            # G16 empty-output guard — never stream an empty reply.
            safe_text, was_empty = wire.empty_output_guard(out.text)
            # G16 wire-decision audit — ONE structured, body-free line per turn.
            wire.audit_turn(
                tier=out.tier, safety_path_taken=out.safety_action,
                chunk_ids=out.chunk_ids, memory_ids=out.memory_ids, empty_guarded=was_empty,
            )
            yield _sse({"type": "meta", "tier": out.tier.value, "crisis": out.tier is Tier.RED})
            for piece in engine.chunk_text(safe_text):
                yield _sse({"type": "token", "text": piece})
            yield _sse({"type": "done", "tier": out.tier.value})

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # -- gated: nightly check-in ------------------------------------------

    @app.post("/checkin", dependencies=[Depends(require_device)])
    async def checkin(request: Request) -> JSONResponse:
        payload = await _json(request)
        sess = _get_or_create_session(payload.get("session_id"))
        try:
            statedb.start_session(sess.session_id, is_test_traffic=sess.test_traffic)
        except Exception:  # noqa: BLE001
            pass
        mood = _as_mood(payload.get("mood"))
        if mood is not None:
            _record_mood(sess, "open", mood)
        # A FIXED, non-interpolated opener (no therapy data on this path).
        return JSONResponse({
            "session_id": sess.session_id,
            "opener": "Winding down? No agenda — how was today, honestly? Even a word or two is enough.",
        })

    # -- gated: homework --------------------------------------------------

    @app.get("/homework", dependencies=[Depends(require_device)])
    async def homework_list() -> JSONResponse:
        try:
            items = statedb.open_homework()
        except Exception:  # noqa: BLE001
            items = []
        return JSONResponse({"homework": [
            {"id": h.id, "title": h.title, "assigned_date": h.assigned_date,
             "due": h.due, "status": h.status}
            for h in items
        ]})

    @app.post("/homework/{hw_id}/done", dependencies=[Depends(require_device)])
    async def homework_done(hw_id: str) -> JSONResponse:
        try:
            ok = statedb.mark_homework_done(hw_id)
        except Exception:  # noqa: BLE001
            ok = False
        return JSONResponse({"ok": ok})

    # -- gated: continuity ------------------------------------------------

    @app.get("/continuity", dependencies=[Depends(require_device)])
    async def continuity() -> JSONResponse:
        text = _continuity.load_continuity_text()
        return JSONResponse({"continuity": text, "greeting": engine.greeting()})

    # -- gated: export/review (Phase 7 stub) ------------------------------

    @app.post("/export/review", dependencies=[Depends(require_device)])
    async def export_review(request: Request) -> JSONResponse:
        payload = await _json(request)
        return JSONResponse({
            "ok": False,
            "status": "stub",
            "message": "Prep-for-Shreya export lands in a later phase. Nothing was generated.",
            "range": {"from": payload.get("from"), "to": payload.get("to")},
        })

    # -- gated: WebAuthn registration stub (D3 rider 3) -------------------

    @app.post("/webauthn/register", dependencies=[Depends(require_device)])
    async def webauthn_register() -> JSONResponse:
        """Stub the passkey registration the tailscale HTTPS origin will make real.

        On the plain-loopback dev origin this just acknowledges; the PWA nags every open until
        registration succeeds (D3 rider 3). Over ``tailscale serve`` (HTTPS) the browser's real
        WebAuthn ceremony replaces this stub.
        """
        return JSONResponse({"ok": True, "stub": True,
                             "note": "Passkey registration is real over the tailscale HTTPS origin."})

    return app


# ---------------------------------------------------------------------------
# Small request helpers
# ---------------------------------------------------------------------------


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _as_mood(value: object) -> int | None:
    try:
        m = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return m if 1 <= m <= 10 else None


def _record_mood(sess: RoomSession, phase: str, mood: int) -> None:
    try:
        statedb.record_mood(phase, mood, session_id=sess.session_id)
    except Exception:  # noqa: BLE001
        pass


#: The module-level app for ``uvicorn dr_alex.alexd:app``.
app = create_app()


# ---------------------------------------------------------------------------
# Foreground dev server (`dr-alex serve`) — pidfile + loopback hard-assert.
# ---------------------------------------------------------------------------


def pidfile_path() -> Path:
    from dr_alex import paths

    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / "alexd.pid"


def _write_pidfile() -> Path:
    p = pidfile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    p.write_text(str(os.getpid()), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def _remove_pidfile() -> None:
    try:
        pidfile_path().unlink()
    except OSError:
        pass


def serve(host: str = HOST, port: int = PORT, *, log_level: str = "info") -> None:
    """Run alexd in the foreground for dev. Hard-asserts a loopback bind (D3 rider 1)."""
    import uvicorn

    require_loopback(host)  # refuse 0.0.0.0 / LAN / any tunnel address
    _write_pidfile()

    def _bye(*_a):  # pragma: no cover - signal path
        _remove_pidfile()
        raise SystemExit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _bye)
        except (ValueError, OSError):  # pragma: no cover - not on the main thread
            pass

    print(f"alexd → http://{host}:{port}/  (The Room; loopback-only, Ctrl-C to stop)")
    try:
        # access_log stays on: uvicorn logs method+path+status only — content lives in POST
        # bodies, never in the URL/query string (R3), so access logs are body-free.
        uvicorn.run(app, host=host, port=port, log_level=log_level, access_log=True)
    finally:
        _remove_pidfile()
