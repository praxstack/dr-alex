"""Live memctl integration — the real bridge, not a fake.

Two proofs that need the actual store toolchain:
  1. **G14 as-of semantics** end-to-end: a superseded fixture fact NEVER reaches Dr. Alex's
     assembled context (written into a THROWAWAY store — the live store is never touched).
  2. **Recall-gate smoke** (read-only): the ``dr-alex`` identity opens ``sensitivity_ceiling
     =high`` against the LIVE store, and a non-allowlisted identity is hard-refused.

Skipped automatically when ``uv`` or the memctl project isn't available.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dr_alex import memory, memstore
from dr_alex.statefile import SessionState

_AGENT_MEMORY_ROOT = Path(memstore.agent_memory_root())
_MEMCTL_PROJECT = _AGENT_MEMORY_ROOT / "tools" / "memctl"
_RULES = _AGENT_MEMORY_ROOT / "tools" / "scrub" / "rules.yaml"

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None or not _MEMCTL_PROJECT.is_dir() or not _RULES.is_file(),
    reason="live memctl toolchain (uv + memctl project + rules.yaml) not available",
)

_UTC = _dt.timezone.utc


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def throwaway_store(tmp_path, monkeypatch):
    """A fresh, git-initialized memctl store the bridge writes into (never the live store)."""
    root = tmp_path / "store"
    for sub in ("memories/user", "memories/feedback", "memories/project",
                "memories/reference", "quarantine", "archive", "inbox"):
        (root / sub).mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "gc.auto", "0")
    (root / ".gitignore").write_text(".index/\n.memctl.lock\n")
    _git(root, "add", ".gitignore")
    _git(root, "-c", "user.name=test", "-c", "user.email=test@local", "commit", "-q", "-m", "init")
    pepper = tmp_path / "pepper"
    pepper.write_bytes(b"\x01\x02" * 16)

    # Point memctl (via inherited env) at the throwaway store; re-enable memory.
    monkeypatch.setenv("MEMCTL_ROOT", str(root))
    monkeypatch.setenv("MEMCTL_PEPPER_FILE", str(pepper))
    monkeypatch.setenv("MEMCTL_RULES_FILE", str(_RULES))
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "0")
    monkeypatch.delenv("MEMCTL_AGENT", raising=False)
    monkeypatch.delenv("MEMCTL_CLIENT", raising=False)
    return root


def test_g14_superseded_fact_never_reaches_context(throwaway_store) -> None:
    # Write a durable therapy fact, then supersede it with a corrected version.
    first = memstore.remember(
        "Behavioral activation reliably lifts Prax's morning lows.",
        tags=["therapy"], sensitivity="high", importance=70,
    )
    assert first.ok, f"remember failed: {first.error}"

    corrected = memstore.supersede(
        first.id,
        "Behavioral activation helps Prax's morning lows only above mood 3 out of 10.",
        reason="refined efficacy condition", tags=["therapy"], sensitivity="high", importance=70,
    )
    assert corrected.ok, f"supersede failed: {corrected.error}"

    # Assemble the session-start context through the REAL recall bridge.
    ctx = memory.assemble(
        SessionState(last_topic="behavioral activation"),
        now=_dt.datetime.now(_UTC),
        recall_fn=memstore.recall,
    )
    block = ctx.personal_memory_block or ""
    # The corrected (active) fact is present; the superseded one is gone (G14).
    assert "only above mood 3" in block
    assert "reliably lifts" not in block


def _memctl(*args: str, agent: str, client: str):
    argv = ["uv", "run", "--project", str(_MEMCTL_PROJECT), "memctl",
            "--agent", agent, "--client", client, "--json", *args]
    return subprocess.run(argv, capture_output=True, text=True)


def test_live_recall_gate_smoke() -> None:
    """Read-only against the LIVE store: dr-alex opens ceiling=high; codex is refused."""
    ok = _memctl("recall", "anxiety", "-k", "1", "--sensitivity-ceiling", "high",
                 agent="dr-alex", client="dr-alex")
    assert ok.returncode == 0, ok.stderr
    # Valid JSON list (possibly empty) — the gate opened, no refusal.
    parsed = json.loads(ok.stdout or "[]")
    assert isinstance(parsed, list)

    refused = _memctl("recall", "anxiety", "-k", "1", "--sensitivity-ceiling", "high",
                      agent="codex", client="mcp")
    assert refused.returncode != 0
    assert "refused" in (refused.stderr or "").lower()
