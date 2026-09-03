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

import asyncio
import json
import logging
import mimetypes
import os
import shutil
import signal
import sqlite3
import threading as _threading
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.concurrency import run_in_threadpool

from dr_alex import (
    config,
    engine,
    fanout,
    llm,
    memstore,
    pairing,
    statedb,
    telemetry,
    timeutil,
    ulid,
    wire,
)
from dr_alex import (
    continuity as _continuity,
)
from dr_alex import (
    debounce as _debounce,
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
        self.transcript_policy = "legacy"
        self.risk_tier_max = Tier.GREEN
        self.mood_phase = "open"
        # Coalesced fragments that a timer/cap flush produced with no live request to stream
        # them back. They are NOT dropped — the next /turn prepends them so the buffered
        # thought still reaches one considered turn (D10). Guarded: the flush callback fires
        # from the debounce timer thread.
        self._pending_coalesced: list[str] = []
        self._pending_lock = _threading.Lock()
        self.debounce = _debounce.DebounceBuffer(flush_callback=self._absorb_flush)

    def _absorb_flush(self, payload: _debounce.FlushPayload) -> None:
        """Timer/cap flush handoff: retain the coalesced text instead of discarding it (D10)."""
        if payload.text:
            with self._pending_lock:
                self._pending_coalesced.append(payload.text)

    def take_pending(self) -> str:
        """Drain and join any coalesced-but-undelivered fragments (empty string if none)."""
        with self._pending_lock:
            if not self._pending_coalesced:
                return ""
            text = "\n".join(self._pending_coalesced)
            self._pending_coalesced.clear()
            return text

    def assemble_memory(self) -> None:
        """Best-effort session-start memory (G20). Degrades to the base prompt on any error."""
        if not memstore.memory_enabled():
            return
        try:
            mem = engine.assemble_startup_memory()
            self.system_prompt = engine.system_prompt_with_memory(mem)
            self.memory_ids = list(mem.recalled_ids)
        except Exception as exc:  # noqa: BLE001 — a broken store must never break session start
            # Body-free (R3): the exception CLASS only, never the store contents.
            _log.warning("session-start memory assembly failed: %s", type(exc).__name__)


_sessions: dict[str, RoomSession] = {}


def _iso_now() -> str:
    return timeutil.now_iso()


def _new_session_id() -> str:
    return ulid.new()


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
) -> pairing.DevicePrincipal:
    """FastAPI dependency: 401 unless a valid, non-revoked device token is presented."""
    principal = pairing.resolve_device_token(x_dr_alex_device_token)
    if principal is None:
        _log.info("event=authorization_denial source=pwa count=1")
        raise HTTPException(status_code=401, detail="device not paired")
    return principal


def _owner_matches_principal(
    owner: statedb.SessionOwner, principal: pairing.DevicePrincipal
) -> bool:
    return (
        owner.actor_principal == principal.actor_principal
        and owner.subject_id == pairing.local_subject_id()
        and owner.source == "pwa"
    )


def _require_active_owner(
    session_id: str | None, principal: pairing.DevicePrincipal
) -> statedb.SessionOwner:
    """Return the matching active PWA owner without adopting or reopening an ID."""
    if not isinstance(session_id, str) or not statedb.valid_session_id(session_id):
        raise HTTPException(status_code=404, detail="session_not_found")
    try:
        owner = statedb.get_session_owner(session_id)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="policy_state_unavailable") from exc
    if (
        owner is None
        or owner.ended_at is not None
        or not _owner_matches_principal(owner, principal)
    ):
        if owner is not None:
            _log.info("event=owner_mismatch source=pwa count=1")
        raise HTTPException(status_code=404, detail="session_not_found")
    return owner


def _require_end_owner(
    session_id: object, principal: pairing.DevicePrincipal
) -> tuple[statedb.SessionOwner, statedb.FinalizationOperation | None]:
    if not isinstance(session_id, str) or not statedb.valid_session_id(session_id):
        raise HTTPException(status_code=404, detail="session_not_found")
    try:
        owner = statedb.get_session_owner(session_id)
        operation = statedb.get_finalization_operation(session_id)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="policy_state_unavailable") from exc
    if (
        owner is None
        or not _owner_matches_principal(owner, principal)
        or (operation is None and (owner.ended_at is not None or session_id not in _sessions))
    ):
        if owner is not None:
            _log.info("event=owner_mismatch source=pwa count=1")
        raise HTTPException(status_code=404, detail="session_not_found")
    return owner, operation


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _refresh_transcript_policy(sess: RoomSession) -> statedb.EffectiveConsent | None:
    """Resolve the enforced PWA policy; legacy surfaces and defaults stay unchanged."""
    if not config.consent_enforcement_enabled():
        sess.transcript_policy = "legacy"
        return None
    try:
        consent = statedb.resolve_consent(pairing.local_subject_id(), "pwa")
    except Exception as exc:  # noqa: BLE001 — policy failure must deny without breaking a turn
        _log.warning("transcript policy resolution failed: %s", type(exc).__name__)
        consent = statedb.EffectiveConsent()
    sess.transcript_policy = "retain" if consent.transcript_retention else "deny"
    return consent


async def _recover_finalizations(subject_id: str, source: str, seams) -> bool:
    """Resume this subject's unfinished synthetic operations within the startup budget."""
    try:
        session_ids = statedb.recoverable_finalization_sessions(subject_id, source)
    except Exception as exc:  # noqa: BLE001 — degraded recovery must not break session start
        _log.warning(
            "event=finalization_recovery source=%s status=recovery_degraded error_class=%s",
            source,
            type(exc).__name__,
        )
        return False
    if not session_ids:
        return True

    async def recover() -> None:
        for session_id in session_ids:
            await run_in_threadpool(
                fanout.finalize_authorized_session,
                session_id,
                subject_id,
                source,
                synthetic_seams=seams,
            )

    try:
        await asyncio.wait_for(recover(), timeout=config.recovery_timeout_seconds())
        return True
    except TimeoutError:
        _log.warning(
            "event=finalization_recovery source=%s status=recovery_degraded "
            "error_class=TimeoutError",
            source,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — degraded recovery must not break session start
        _log.warning(
            "event=finalization_recovery source=%s status=recovery_degraded error_class=%s",
            source,
            type(exc).__name__,
        )
        return False


def _log_finalization(
    source: str,
    status: str,
    *,
    duplicate: bool,
    started: float,
    error_class: str | None,
) -> None:
    try:
        pending_count, oldest_pending_seconds = statedb.finalization_pending_stats(source)
    except sqlite3.Error:
        pending_count, oldest_pending_seconds = -1, -1
    _log.info(
        "event=finalization source=%s status=%s pending_count=%d "
        "oldest_pending_seconds=%d duplicate_end_count=%d duration_ms=%d error_class=%s",
        source,
        status,
        pending_count,
        oldest_pending_seconds,
        int(duplicate),
        int((time.perf_counter() - started) * 1000),
        error_class or "none",
    )


def _run_turn_blocking(sess: RoomSession, text: str) -> engine.TurnOutcome:
    """Run the SINGLE turn function on a worker thread (it may spawn the model subprocess)."""
    _refresh_transcript_policy(sess)

    def current_transcript_policy() -> str:
        _refresh_transcript_policy(sess)
        return sess.transcript_policy

    out = engine.run_turn(
        text,
        history=list(sess.history),
        session=sess.state,
        session_id=sess.session_id,
        system_prompt_override=sess.system_prompt,
        memory_ids=sess.memory_ids,
        transcript_policy=sess.transcript_policy,
        transcript_policy_resolver=current_transcript_policy,
    )
    if out.tier is Tier.RED or (out.tier is Tier.AMBER and sess.risk_tier_max is Tier.GREEN):
        sess.risk_tier_max = out.tier
    # Maintain conversation history for GREEN/AMBER turns (RED is not a conversational turn).
    if out.tier is not Tier.RED:
        sess.history.append(llm.Message(role="user", content=text))
        sess.history.append(llm.Message(role="assistant", content=out.text))
    return out


# ---------------------------------------------------------------------------
# Static asset serving (the PWA shell — ungated, self-contained, offline-cacheable)
# ---------------------------------------------------------------------------


def _health_checks() -> dict[str, bool]:
    """Cheap, read-only subsystem probes for ``/healthz``. Never raises, never writes."""
    checks: dict[str, bool] = {}
    try:  # the PWA shell the phone loads
        checks["room_shell"] = (ROOM_DIR / "index.html").is_file()
    except OSError:
        checks["room_shell"] = False
    try:  # the offline crisis card — the one surface that must exist at 3am
        checks["crisis_card"] = (ROOM_DIR / "crisis.html").is_file() and bool(
            crisis_card.render_text().strip()
        )
    except Exception:  # noqa: BLE001
        checks["crisis_card"] = False
    try:
        checks["statedb"] = statedb.healthy()
    except Exception:  # noqa: BLE001
        checks["statedb"] = False
    return checks


def _read_room(name: str) -> str | None:
    p = (ROOM_DIR / name).resolve()
    # containment: never serve outside ROOM_DIR
    if ROOM_DIR not in p.parents and p != ROOM_DIR:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# Response-hardening headers for the self-contained PWA shell + assets (D19). The Room fetches
# nothing off-origin, so a strict CSP holds: everything is 'self' except the inline <style> in
# the safety-critical crisis card ('unsafe-inline' for styles only — never scripts) and the
# manifest's data: icon (img-src data:). script-src stays 'self' (no inline scripts anywhere).
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _secure_headers(extra: dict | None = None) -> dict:
    """Merge the response-hardening headers with any per-response headers (D19)."""
    headers = dict(_SECURITY_HEADERS)
    if extra:
        headers.update(extra)
    return headers


def _asset_response(name: str) -> Response:
    body = _read_room(name)
    if body is None:
        raise HTTPException(status_code=404, detail="not found")
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if name.endswith(".js"):
        ctype = "text/javascript"
    extra = {}
    # The service worker must be allowed to control the whole origin scope.
    if name == "sw.js":
        extra["Service-Worker-Allowed"] = "/"
    return Response(content=body, media_type=ctype, headers=_secure_headers(extra))


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(_app: FastAPI):  # pragma: no cover - lifecycle
    """Own the background log-trimmer for exactly as long as the app is serving.

    Uses the lifespan protocol rather than the deprecated ``@app.on_event`` hooks, so this
    keeps working when Starlette drops them. Startup must never be able to fail here: a
    logging-hygiene task that prevents the daemon from booting is strictly worse than an
    unbounded log file.
    """
    task: asyncio.Task | None = None
    try:
        task = asyncio.create_task(_trim_launchd_logs_forever())
    except RuntimeError as exc:  # no running loop (shouldn't happen under uvicorn)
        _log.warning("log trimmer not started: %s", type(exc).__name__)
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            # Wait for the child WITHOUT letting its cancellation propagate as ours: a bare
            # `suppress(CancelledError)` around `await task` also swallows an outer cancel
            # aimed at this lifespan, which would eat the shutdown signal itself.
            done, _pending = await asyncio.wait({task}, timeout=5)
            if not done:
                _log.warning("log trimmer did not stop within 5s; abandoning it")


def create_app() -> FastAPI:
    app = FastAPI(
        title="alexd",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

    # -- ungated: static shell + manifest + service worker ----------------

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        body = _read_room("index.html")
        if body is None:  # pragma: no cover - room assets are shipped with the package
            raise HTTPException(status_code=500, detail="app shell missing")
        return HTMLResponse(content=body, headers=_secure_headers())

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
        return HTMLResponse(content=body, headers=_secure_headers())

    # -- ungated: health --------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Real subsystem health. Shape is backward-compatible: ``ok`` is still True when well.

        Checks only what a 3am turn actually needs, and only with cheap read-only probes:
        the PWA shell + the static crisis card (the one surface that must never be missing —
        this daemon crash-looped 1,810 times over exactly that class of fault), and the state
        store. Absent-but-lazily-created is NOT a fault. Never raises; ``checks`` is additive.
        """
        checks = _health_checks()
        return JSONResponse(
            {
                "ok": all(checks.values()),
                "service": "alexd",
                "loopback": True,
                "checks": checks,
            }
        )

    # /readyz and /livez are aliases of /healthz — something local polls those
    # names and logs 404 spam against them; same body, no new logic.
    app.add_api_route("/readyz", healthz, methods=["GET"])
    app.add_api_route("/livez", healthz, methods=["GET"])

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
        except pairing.PairingLockedOut as exc:
            raise HTTPException(
                status_code=429, detail="too many attempts; try again later"
            ) from exc
        if dev is None:
            raise HTTPException(status_code=401, detail="invalid or expired pairing code")
        return JSONResponse({"device_id": dev.id, "device_token": dev.token})

    # -- gated: session lifecycle -----------------------------------------

    @app.post("/session/start")
    async def session_start(
        request: Request,
        principal: pairing.DevicePrincipal = Depends(require_device),
    ) -> JSONResponse:
        payload = await _json(request)
        enforcement = config.consent_enforcement_enabled()
        consent_supplied = "consent" in payload
        if consent_supplied and not enforcement:
            raise HTTPException(status_code=409, detail="consent_feature_disabled")
        if consent_supplied and not config.allow_test_consent():
            raise HTTPException(status_code=403, detail="consent_channel_not_approved")
        subject_id = pairing.local_subject_id()
        requested_session_id = payload.get("session_id")
        if requested_session_id is not None and not statedb.valid_session_id(requested_session_id):
            raise HTTPException(status_code=422, detail="invalid_session_id")
        session_id = requested_session_id or _new_session_id()
        try:
            owner = statedb.create_session_owner_and_consent(
                session_id,
                subject_id=subject_id,
                actor_principal=principal.actor_principal,
                source="pwa",
                consent=payload["consent"] if consent_supplied else None,
            )
        except statedb.ConsentValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.code) from exc
        except sqlite3.Error as exc:
            detail = "consent_store_unavailable" if consent_supplied else "policy_state_unavailable"
            raise HTTPException(status_code=503, detail=detail) from exc
        if owner is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        sess = _get_or_create_session(session_id)
        consent = _refresh_transcript_policy(sess)
        try:
            statedb.start_session(sess.session_id, is_test_traffic=sess.test_traffic)
        except Exception as exc:  # noqa: BLE001 — telemetry never blocks a session
            _log.warning("start_session telemetry failed: %s", type(exc).__name__)
        # Optional arriving mood chip (1–10).
        mood = _as_mood(payload.get("mood"))
        if mood is not None:
            _record_mood(sess, "open", mood)
        recovery_complete = True
        if enforcement:
            recovery_complete = await _recover_finalizations(
                subject_id,
                "pwa",
                getattr(request.app.state, "synthetic_finalization_seams", None),
            )
        # Session-start memory context (G20), off the request's hot path is not needed here —
        # it's a one-time assemble and degrades safely. A timed-out recovery may still own a
        # worker thread, so keep the base prompt rather than read a sink while it is mutating.
        if recovery_complete:
            await run_in_threadpool(sess.assemble_memory)
        ack = None
        try:
            ack = telemetry.take_repair_ack()
        except Exception as exc:  # noqa: BLE001
            _log.warning("repair-ack fetch failed: %s", type(exc).__name__)
            ack = None
        response: dict[str, object] = {
            "session_id": sess.session_id,
            "greeting": engine.greeting(),
            "repair_ack": ack,
        }
        if enforcement:
            consent = consent or statedb.EffectiveConsent()
            response["consent_status"] = {
                "transcript_retention": "granted" if consent.transcript_retention else "denied",
                "durable_memory": "granted" if consent.durable_memory else "denied",
                "cross_surface_recall": "granted" if consent.cross_surface_recall else "denied",
            }
            response["consent_active"] = any(
                (consent.transcript_retention, consent.durable_memory, consent.cross_surface_recall)
            )
        return JSONResponse(response)

    @app.post("/session/end")
    async def session_end(
        request: Request,
        principal: pairing.DevicePrincipal = Depends(require_device),
    ) -> JSONResponse:
        payload = await _json(request)
        sid = payload.get("session_id")
        owner, existing_operation = _require_end_owner(sid, principal)
        sess = _sessions.get(sid) if sid else None
        mood = _as_mood(payload.get("mood"))
        if sess is not None and mood is not None:
            _record_mood(sess, "close", mood)
        # D10: drain any coalesced-but-undelivered text before the session is dropped.
        # Timer/cap flushes park fragments in ``_pending_coalesced`` with no live /turn to
        # stream them; anything still in the debounce window is folded in too. Without this,
        # a session that finalizes with pending fragments silently loses that thought. One
        # final considered turn runs it through the SAME safety-first pipeline — run_turn
        # re-triages, so a crisis leftover still routes through the RED short-circuit (the
        # crisis bypass is preserved, not weakened).
        if sess is not None:
            _refresh_transcript_policy(sess)
            buffered = sess.debounce.flush_now(sess.session_id)
            leftover = "\n".join(
                p for p in (sess.take_pending(), buffered.text if buffered else "") if p
            ).strip()
            if leftover:
                try:
                    await run_in_threadpool(_run_turn_blocking, sess, leftover)
                except Exception as exc:  # noqa: BLE001 — finalize must never fail on a leftover turn
                    # NEVER log ``leftover`` itself (R3) — the exception class only.
                    _log.warning("session-end leftover turn failed: %s", type(exc).__name__)
        receipt = None
        if sid and config.consent_enforcement_enabled():
            finalization_started = time.perf_counter()
            try:
                receipt = await run_in_threadpool(
                    fanout.finalize_authorized_session,
                    sid,
                    owner.subject_id,
                    owner.source,
                    risk_tier_max=sess.risk_tier_max.value if sess is not None else "GREEN",
                    turns=[(message.role, message.content) for message in sess.history]
                    if sess is not None
                    else None,
                    started_at=sess.started_at if sess is not None else "",
                    synthetic_seams=getattr(
                        request.app.state, "synthetic_finalization_seams", None
                    ),
                )
            except Exception as exc:
                _log_finalization(
                    owner.source,
                    "recovery_pending",
                    duplicate=existing_operation is not None,
                    started=finalization_started,
                    error_class=type(exc).__name__,
                )
                raise
            _log_finalization(
                owner.source,
                receipt.status,
                duplicate=existing_operation is not None,
                started=finalization_started,
                error_class=receipt.error_class,
            )
        if sid and owner.ended_at is None:
            try:
                closed = statedb.close_session_owner(
                    sid,
                    subject_id=owner.subject_id,
                    actor_principal=owner.actor_principal,
                    source=owner.source,
                )
            except sqlite3.Error as exc:
                raise HTTPException(status_code=503, detail="policy_state_unavailable") from exc
            if not closed:
                try:
                    current_owner = statedb.get_session_owner(sid)
                except sqlite3.Error as exc:
                    raise HTTPException(status_code=503, detail="policy_state_unavailable") from exc
                if (
                    current_owner is None
                    or current_owner.ended_at is None
                    or current_owner.subject_id != owner.subject_id
                    or current_owner.actor_principal != owner.actor_principal
                    or current_owner.source != owner.source
                ):
                    raise HTTPException(status_code=404, detail="session_not_found")
            else:
                try:
                    statedb.end_session(sid)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("end_session telemetry failed: %s", type(exc).__name__)
                _sessions.pop(sid, None)
        if receipt is None:
            return JSONResponse({"ok": True})
        incomplete = receipt.status in {"finalization_unavailable", "recovery_pending"}
        return JSONResponse(
            {
                "ok": not incomplete,
                "complete": not incomplete,
                "finalization": {
                    "status": receipt.status,
                    "operation_id": receipt.operation_id,
                    "memory_written": receipt.memory_written,
                    "error_class": receipt.error_class,
                },
            },
            status_code={"finalization_unavailable": 503, "recovery_pending": 202}.get(
                receipt.status, 200
            ),
        )

    # -- gated: the turn (SSE) --------------------------------------------

    @app.post("/turn")
    async def turn(
        request: Request,
        principal: pairing.DevicePrincipal = Depends(require_device),
    ):
        payload = await _json(request)
        session_id = payload.get("session_id")
        _require_active_owner(session_id, principal)
        sess = _sessions.get(session_id) if isinstance(session_id, str) else None
        if sess is None:
            raise HTTPException(status_code=404, detail="session_not_found")
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
        # Also fold in any earlier timer/cap-flushed fragments that had no live request
        # to stream them (D10 — never silently dropped).
        buffered = sess.debounce.flush_now(sess.session_id)
        parts = [p for p in (sess.take_pending(), buffered.text if buffered else "", text) if p]
        coalesced = "\n".join(parts).strip()

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
                tier=out.tier,
                safety_path_taken=out.safety_action,
                chunk_ids=out.chunk_ids,
                memory_ids=out.memory_ids,
                empty_guarded=was_empty,
            )
            yield _sse({"type": "meta", "tier": out.tier.value, "crisis": out.tier is Tier.RED})
            for piece in engine.chunk_text(safe_text):
                yield _sse({"type": "token", "text": piece})
            yield _sse({"type": "done", "tier": out.tier.value})

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # -- gated: nightly check-in ------------------------------------------

    @app.post("/checkin")
    async def checkin(
        request: Request,
        principal: pairing.DevicePrincipal = Depends(require_device),
    ) -> JSONResponse:
        payload = await _json(request)
        session_id = payload.get("session_id")
        if session_id:
            _require_active_owner(session_id, principal)
        else:
            session_id = _new_session_id()
            try:
                owner = statedb.create_session_owner(
                    session_id,
                    subject_id=pairing.local_subject_id(),
                    actor_principal=principal.actor_principal,
                    source="pwa",
                )
            except sqlite3.Error as exc:
                raise HTTPException(status_code=503, detail="policy_state_unavailable") from exc
            if owner is None:
                raise HTTPException(status_code=503, detail="policy_state_unavailable")
        sess = _get_or_create_session(session_id)
        try:
            statedb.start_session(sess.session_id, is_test_traffic=sess.test_traffic)
        except Exception as exc:  # noqa: BLE001
            _log.warning("checkin start_session telemetry failed: %s", type(exc).__name__)
        mood = _as_mood(payload.get("mood"))
        if mood is not None:
            _record_mood(sess, "open", mood)
        # A FIXED, non-interpolated opener (no therapy data on this path).
        return JSONResponse(
            {
                "session_id": sess.session_id,
                "opener": "Winding down? No agenda — how was today, honestly? Even a word or two is enough.",
            }
        )

    # -- gated: homework --------------------------------------------------

    @app.get("/homework", dependencies=[Depends(require_device)])
    async def homework_list() -> JSONResponse:
        try:
            items = statedb.open_homework()
        except Exception as exc:  # noqa: BLE001
            _log.warning("open_homework failed: %s", type(exc).__name__)
            items = []
        return JSONResponse(
            {
                "homework": [
                    {
                        "id": h.id,
                        "title": h.title,
                        "assigned_date": h.assigned_date,
                        "due": h.due,
                        "status": h.status,
                    }
                    for h in items
                ]
            }
        )

    @app.post("/homework/{hw_id}/done", dependencies=[Depends(require_device)])
    async def homework_done(hw_id: str) -> JSONResponse:
        try:
            ok = statedb.mark_homework_done(hw_id)
        except Exception as exc:  # noqa: BLE001
            _log.warning("mark_homework_done failed: %s", type(exc).__name__)
            ok = False
        return JSONResponse({"ok": ok})

    # -- gated: continuity ------------------------------------------------

    @app.get("/continuity", dependencies=[Depends(require_device)])
    async def continuity() -> JSONResponse:
        text = _continuity.load_continuity_text()
        return JSONResponse({"continuity": text, "greeting": engine.greeting()})

    # -- gated: export/review (Phase 7 — real) ----------------------------

    @app.post("/export/review", dependencies=[Depends(require_device)])
    async def export_review(request: Request) -> JSONResponse:
        """Generate a date-ranged export ON THE MAC for print-to-PDF (council D6).

        Body: ``{from, to, redaction}``. With no range, defaults to the last 30 days. The
        generated markdown + self-contained HTML are written locally to ``exports/``; only the
        (date-only) file paths + range are returned — clinical content never crosses the wire.
        """
        from dr_alex import export as _export

        payload = await _json(request)
        redaction = str(payload.get("redaction", "summary"))
        frm = payload.get("from")
        to = payload.get("to")

        def _run() -> _export.ExportResult:
            if frm and to:
                return _export.export_range(str(frm), str(to), redaction=redaction, write=True)
            return _export.review(days=30, redaction=redaction, write=True)

        res = await run_in_threadpool(_run)
        if not res.ok:
            return JSONResponse(
                {"ok": False, "error": res.error or "export failed"}, status_code=400
            )
        return JSONResponse(
            {
                "ok": True,
                "redaction": res.redaction,
                "range": {"from": res.from_date, "to": res.to_date},
                "markdown_path": res.markdown_path,
                "html_path": res.html_path,
                "note": "Generated on the Mac. Open the HTML and print-to-PDF; nothing was sent.",
            }
        )

    # -- gated: WebAuthn registration stub (D3 rider 3) -------------------

    @app.post("/webauthn/register", dependencies=[Depends(require_device)])
    async def webauthn_register() -> JSONResponse:
        """Stub the passkey registration the tailscale HTTPS origin will make real.

        On the plain-loopback dev origin this just acknowledges; the PWA nags every open until
        registration succeeds (D3 rider 3). Over ``tailscale serve`` (HTTPS) the browser's real
        WebAuthn ceremony replaces this stub.
        """
        return JSONResponse(
            {
                "ok": True,
                "stub": True,
                "note": "Passkey registration is real over the tailscale HTTPS origin.",
            }
        )

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
    except Exception as exc:  # noqa: BLE001
        _log.warning("record_mood failed: %s", type(exc).__name__)


#: The module-level app for ``uvicorn dr_alex.alexd:app``.
app = create_app()


# ---------------------------------------------------------------------------
# Foreground dev server (`dr-alex serve`) — pidfile + loopback hard-assert.
# ---------------------------------------------------------------------------


#: The daemon's own rotating log — hard ceiling 4 × 1 MB.
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUPS = 3

#: Ceiling on the launchd-captured stdout/stderr files. launchd holds those fds itself, so the
#: daemon is the only thing that can bound them (see :func:`_trim_launchd_logs`).
_LAUNCHD_LOG_MAX_BYTES = 8_000_000

#: How often the running daemon re-checks that cap. Startup-only trimming bounds nothing on a
#: daemon that stays up for weeks — which is the whole point of this one.
_LAUNCHD_LOG_TRIM_INTERVAL_S = 3600.0

#: The launchd-captured files, as named by ``tools/launchd/com.prax.dralex-alexd.plist``.
_LAUNCHD_LOG_NAMES = ("dr-alex-alexd.err.log", "dr-alex-alexd.out.log")


def log_dir() -> Path:
    """The app's own ``logs/`` dir — a real, persistent directory, never ``/tmp``.

    ``/tmp`` is wiped at every boot on this machine, so a postmortem for an overnight failure
    was permanently unrecoverable the moment the Mac restarted. This dir is gitignored and the
    hygiene guard asserts no log ever enters git.
    """
    from dr_alex import paths

    found = paths.find("logs")
    return found if found is not None else (Path(__file__).resolve().parent.parent / "logs")


def _configure_daemon_logging() -> None:
    """Give the body-free audit/trace loggers a real sink. Daemon entrypoint only.

    Without this, ``dr_alex.wire`` / ``dr_alex.trace`` inherit root's WARNING level and have no
    handler, so every per-turn INFO audit line is dropped before any handler sees it (uvicorn
    configures only its own loggers and never root). Call sites are untouched — this attaches
    one level + two handlers to the ``dr_alex`` parent.

    Ordering is deliberate: stderr FIRST, because it needs no path to resolve and no file to
    open, so logging always works even if the filesystem is hostile. The rotating file is added
    on top, best-effort — if it cannot be opened the daemon logs a warning and runs stderr-only.
    Given the 1,810-crash-loop-from-a-missing-file history, opening a file at boot must never
    be able to take the daemon down.
    """
    lg = logging.getLogger("dr_alex")
    if any(getattr(h, "_dralex_audit_sink", False) for h in lg.handlers):
        return  # idempotent — serve() may run more than once in a process
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream = logging.StreamHandler()  # defaults to sys.stderr
    stream.setFormatter(fmt)
    stream._dralex_audit_sink = True  # type: ignore[attr-defined]
    lg.addHandler(stream)
    lg.setLevel(logging.INFO)

    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        target = d / "alexd.log"
        rotating = RotatingFileHandler(
            target,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUPS,
            encoding="utf-8",
        )
        rotating.setFormatter(fmt)
        rotating._dralex_audit_sink = True  # type: ignore[attr-defined]
        lg.addHandler(rotating)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001 — a log file must never block the daemon
        lg.warning("file log unavailable, stderr only: %s", type(exc).__name__)


def _trim_launchd_logs() -> None:
    """Bound the launchd-captured stdout/stderr files, preserving the previous content.

    launchd opens those paths itself, in append mode, BEFORE exec — so a plist-side ``mv``
    would send this run's output into the rotated file, and nothing outside this process can
    rotate them at all. Copy-aside + truncate-in-place is the one form that works with the fd
    launchd already holds: an O_APPEND write resumes at the new EOF, so there is no sparse hole
    and no lost line. Runs once at startup and only above the cap; failure is a no-op.
    """
    for name in _LAUNCHD_LOG_NAMES:
        try:
            p = log_dir() / name
            if not p.is_file() or p.stat().st_size <= _LAUNCHD_LOG_MAX_BYTES:
                continue
            shutil.copy2(str(p), str(p) + ".1")
            os.truncate(str(p), 0)
        except OSError:
            continue


async def _trim_launchd_logs_forever() -> None:
    """Re-check the launchd log cap on a timer for as long as the daemon lives.

    Trimming only at startup bounds nothing: this daemon is meant to stay up for weeks, and
    the file it cannot rotate is the one carrying every uvicorn access line. A restart-driven
    cap is a cap that only applies to daemons which crash — precisely the ones that were
    already visible. Cancelled at shutdown; never raises, because a logging-hygiene task must
    never be able to take down the service it is logging for.
    """
    while True:
        try:
            await asyncio.sleep(_LAUNCHD_LOG_TRIM_INTERVAL_S)
        except asyncio.CancelledError:  # shutdown
            raise
        try:
            await asyncio.to_thread(_trim_launchd_logs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — hygiene must never kill the daemon
            _log.warning("launchd log trim failed: %s", type(exc).__name__)


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
    _configure_daemon_logging()
    _trim_launchd_logs()
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
