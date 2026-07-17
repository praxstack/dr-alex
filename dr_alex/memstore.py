"""The memctl bridge — Dr. Alex's ONLY connection to the canonical memory store.

Phase 3 ("Remembers") wires Dr. Alex to the durable store at ``~/agent-memory`` through
the ``memctl`` CLI, exactly as the architecture requires: *all* store access goes through
memctl (store contract invariant 3 — never touch ``memories/`` files directly), and the
recall of ``sensitivity:high`` therapy memories rides the gated ``--sensitivity-ceiling
high`` scope that the store authorizes ONLY for the ``dr-alex`` identity (council ruling
2026-07-17). We shell out to the CLI with ``--client dr-alex`` (never a per-turn MCP
server): that identity opens the ceiling via the store's agent allowlist AND keeps
Dr. Alex at least privilege (``is_cli`` false → the store enforces the importance clamp
and refuses pinning), while we ALSO clamp importance ≤80 here as belt-and-suspenders.

Directive 1 (single model entrypoint) note: this module spawns a subprocess, but it runs
``memctl`` / the store's ``scrub`` — **never** the model. Exactly one private function,
:func:`_run`, spawns anything at all; a static test asserts it is the only subprocess site
outside ``llm.complete`` and that this file never references the model binary.

Every read degrades to *honest emptiness* rather than raising: a store that is missing,
slow, or erroring must never break a session. Writes report failure to the caller (which
logs it, never blocks). Nothing in here ever logs a message body, a memory body, or a
therapy fact — structured status only (R3).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Identity + configuration (env-overridable so tests point at a throwaway store)
# ---------------------------------------------------------------------------

#: Launch identity. `--client dr-alex` is what the store's ceiling gate allowlists
#: (recall.py HIGH_SENSITIVITY_AGENTS) AND it keeps us out of the human-CLI trust
#: bracket, so the store still enforces the importance clamp on our writes.
AGENT = "dr-alex"
CLIENT = "dr-alex"

#: Durable clinical writes are clamped to importance ≤80 (architecture: "importance
#: clamped ≤80"; store CA-16 also refuses >80 for non-CLI identities). We clamp here
#: too so a caller bug can never even attempt to exceed it.
IMPORTANCE_MAX = 80

_AGENT_MEMORY_ROOT_ENV = "DR_ALEX_AGENT_MEMORY_ROOT"
_STORE_ROOT_ENV = "MEMCTL_ROOT"  # honored by memctl itself; used here for inbox location
_MEMORY_OFF_ENV = "DR_ALEX_MEMORY_OFF"  # kill-switch: degrade to Phase-2 (no store)

_DEFAULT_AGENT_MEMORY_ROOT = "/Users/prax/agent-memory"
_DEFAULT_TIMEOUT = 45


def agent_memory_root() -> str:
    return os.environ.get(_AGENT_MEMORY_ROOT_ENV) or _DEFAULT_AGENT_MEMORY_ROOT


def store_root() -> str:
    """Where memories + inbox live (memctl's own ``MEMCTL_ROOT``, else the project root)."""
    return os.environ.get(_STORE_ROOT_ENV) or agent_memory_root()


def inbox_dir() -> str:
    return os.path.join(store_root(), "inbox")


def memory_enabled() -> bool:
    """False when the kill-switch is set — the tool then behaves like Phase 2 (no memory)."""
    return os.environ.get(_MEMORY_OFF_ENV, "").strip().lower() not in ("1", "true", "yes", "on")


def _memctl_project() -> str:
    return os.path.join(agent_memory_root(), "tools", "memctl")


def _launcher() -> list[str]:
    """The argv prefix that runs ``memctl`` (uv resolves the memctl project's own venv)."""
    return ["uv", "run", "--project", _memctl_project(), "memctl"]


def _python_launcher() -> list[str]:
    """argv prefix to run Python inside the memctl project (for the store's scrub)."""
    return ["uv", "run", "--project", _memctl_project(), "python"]


# ---------------------------------------------------------------------------
# The SOLE subprocess site (see module docstring / test_single_llm_entrypoint).
# ---------------------------------------------------------------------------


@dataclass
class _Proc:
    returncode: int
    stdout: bytes
    stderr: bytes


def _run(argv: list[str], *, input_bytes: bytes | None = None, timeout: int = _DEFAULT_TIMEOUT) -> _Proc:
    """Run one agent-memory subprocess (memctl or its scrub). NEVER the model.

    Returns a small result even on failure; the only exception it lets through is a
    genuinely unexpected OSError, which callers of the *read* path swallow into emptiness.
    """
    proc = subprocess.run(  # noqa: S603 — fixed argv, no shell; the single sanctioned site
        argv,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
    )
    return _Proc(returncode=proc.returncode, stdout=proc.stdout or b"", stderr=proc.stderr or b"")


# ---------------------------------------------------------------------------
# Recall (READ) — validity-filtered, ceiling-gated therapy retrieval.
# ---------------------------------------------------------------------------


@dataclass
class Hit:
    id: str
    type: str
    status: str
    valid_from: str
    invalid_at: str | None
    importance: int
    sensitivity: str
    score: float
    snippet: str

    @classmethod
    def from_dict(cls, d: dict) -> "Hit":
        return cls(
            id=str(d.get("id", "")),
            type=str(d.get("type", "")),
            status=str(d.get("status", "")),
            valid_from=str(d.get("valid_from", "")),
            invalid_at=d.get("invalid_at"),
            importance=int(d.get("importance", 0) or 0),
            sensitivity=str(d.get("sensitivity", "")),
            score=float(d.get("score", 0.0) or 0.0),
            snippet=str(d.get("snippet", "")),
        )


def recall(
    query: str,
    *,
    k: int = 6,
    tag: str | None = "therapy",
    ceiling: str = "high",
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[Hit]:
    """Gated recall of therapy memories. Returns [] on any failure (honest emptiness).

    Uses NO ``--as-of`` flag, so memctl applies its default validity filter
    (``status=active AND valid-as-of-now``) — this is exactly the G14 as-of semantics that
    keeps superseded / invalidated facts out of the assembled context. The high ceiling is
    authorized by the ``dr-alex`` launch identity; for any other identity memctl hard-fails
    (which we, correctly, surface as empty rather than falling back to a wider scope).
    """
    if not memory_enabled():
        return []
    argv = [
        *_launcher(),
        "--agent", AGENT, "--client", CLIENT, "--json",
        "recall", query or "",
        "-k", str(max(int(k), 0)),
        "--sensitivity-ceiling", ceiling,
    ]
    if tag:
        argv += ["--filter", f"tag={tag}"]
    try:
        proc = _run(argv, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    hits: list[Hit] = []
    for row in data:
        if isinstance(row, dict):
            try:
                hits.append(Hit.from_dict(row))
            except (ValueError, TypeError):
                continue
    return hits


# ---------------------------------------------------------------------------
# Remember / supersede (WRITE) — durable clinical learnings.
# ---------------------------------------------------------------------------


@dataclass
class WriteResult:
    ok: bool
    id: str | None = None
    error: str | None = None


def _clamp_importance(importance: int | None) -> int:
    if importance is None:
        return IMPORTANCE_MAX
    return max(0, min(int(importance), IMPORTANCE_MAX))


def _parse_write(proc: _Proc) -> WriteResult:
    try:
        out = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except (ValueError, TypeError):
        out = {}
    if proc.returncode == 0 and isinstance(out, dict) and out.get("id"):
        return WriteResult(ok=True, id=str(out["id"]))
    # Never surface a body; a short, structured reason only (R3).
    reason = None
    if isinstance(out, dict):
        reason = out.get("status") or out.get("reason")
    return WriteResult(ok=False, error=str(reason or f"exit {proc.returncode}"))


def remember(
    body: str,
    *,
    tags: list[str] | None = None,
    sensitivity: str = "high",
    importance: int | None = None,
    memtype: str = "user",
    timeout: int = _DEFAULT_TIMEOUT,
) -> WriteResult:
    """Write ONE durable clinical fact via ``memctl remember`` (one fact per memory).

    Therapy learnings are ``sensitivity:high`` + ``tags:[therapy]`` by default, importance
    clamped ≤80. The store scrubs on the write path, so no external scrub is needed here.
    """
    if not memory_enabled():
        return WriteResult(ok=False, error="memory disabled")
    tag_csv = ",".join(tags or ["therapy"])
    argv = [
        *_launcher(),
        "--agent", AGENT, "--client", CLIENT, "--json",
        "remember",
        "--type", memtype,
        "--tags", tag_csv,
        "--sensitivity", sensitivity,
        "--importance", str(_clamp_importance(importance)),
    ]
    try:
        proc = _run(argv, input_bytes=body.encode("utf-8"), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return WriteResult(ok=False, error=type(exc).__name__)
    return _parse_write(proc)


def supersede(
    target: str,
    body: str,
    *,
    reason: str,
    tags: list[str] | None = None,
    sensitivity: str = "high",
    importance: int | None = None,
    memtype: str = "user",
    timeout: int = _DEFAULT_TIMEOUT,
) -> WriteResult:
    """Correct a durable fact bi-temporally (never an in-place edit / duplicate)."""
    if not memory_enabled():
        return WriteResult(ok=False, error="memory disabled")
    tag_csv = ",".join(tags or ["therapy"])
    argv = [
        *_launcher(),
        "--agent", AGENT, "--client", CLIENT, "--json",
        "supersede", target,
        "--reason", reason,
        "--type", memtype,
        "--tags", tag_csv,
        "--sensitivity", sensitivity,
        "--importance", str(_clamp_importance(importance)),
    ]
    try:
        proc = _run(argv, input_bytes=body.encode("utf-8"), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return WriteResult(ok=False, error=type(exc).__name__)
    return _parse_write(proc)


# ---------------------------------------------------------------------------
# Scrub (WRITE, Channel C) — reuse the store's EXISTING scrub before an inbox drop.
# ---------------------------------------------------------------------------

_SCRUB_PROG = (
    "import sys\n"
    "from memctl import scrub\n"
    "ruleset = scrub.load_ruleset()\n"
    "pepper, _ = scrub.load_pepper()\n"
    "data = sys.stdin.buffer.read()\n"
    "sys.stdout.buffer.write(scrub.scrub_bytes(data, ruleset, pepper).clean)\n"
)


class ScrubError(RuntimeError):
    """The store's scrub could not run. Callers MUST NOT write the unscrubbed document."""


def scrub_document(document: str, *, timeout: int = _DEFAULT_TIMEOUT) -> bytes:
    """Run the store's EXISTING scrub ruleset over a document; return only clean bytes.

    Mirrors ``tools/hooks/session_end.py`` (same rules.yaml + pepper, env-overridable for
    tests). Raises :class:`ScrubError` on any failure so the fan-out skips the inbox write
    rather than ever landing raw therapy content on disk (privacy fails safe).
    """
    argv = [*_python_launcher(), "-c", _SCRUB_PROG]
    try:
        proc = _run(argv, input_bytes=document.encode("utf-8"), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScrubError(f"scrub subprocess failed: {type(exc).__name__}") from exc
    if proc.returncode != 0:
        raise ScrubError(f"scrub exited {proc.returncode}")
    return proc.stdout
