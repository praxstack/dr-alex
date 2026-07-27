"""Directive 3 (binding): git + data hygiene guard. Hard failures.

Clinical and derived data must NEVER be tracked in git, and the clinical-data directory
must be private (0700). R1 also forbids a remote on this repo before final review.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# Paths that must never appear in `git ls-files`.
_FORBIDDEN = (
    re.compile(r"^records/"),
    re.compile(r"^exports/"),
    re.compile(r"(^|/)state\.db"),          # state.db, state.db-wal, …
    re.compile(r"^data/continuity\.md$"),
    re.compile(r"^data/index/"),            # derived book index, rebuildable
    re.compile(r"\.(wav|m4a|mp3|flac)$"),   # audio
    re.compile(r"^inbox/"),                 # session digests
    re.compile(r"^data/session_state\.json$"),   # Phase 3: last_session_at/last_topic + marker
    re.compile(r"^data/\.session_state\.[^/]*\.tmp$"),  # atomic-write temp
    re.compile(r"(^|/)pairing\.db"),             # Phase 5: device-token hashes (auth secrets)
    re.compile(r"(^|/)alexd\.pid$"),             # Phase 5: alexd pidfile
    re.compile(r"(^|/)user-books\.json$"),       # Phase 2b: supplemental drop-in book manifest
    re.compile(r"\.extracted\.txt$"),            # Phase 2b: derived PDF extraction caches
    re.compile(r"^data/improve/"),               # G22: persona self-improvement audit/changelog
    re.compile(r"^logs/.*\.log"),                # daemon logs (body-free, but derived + local)
    re.compile(r"^data/\.(checkin|continuity)\.[^/]*\.tmp$"),  # atomic-write temps
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout


def test_no_clinical_or_derived_data_is_tracked() -> None:
    tracked = _git("ls-files").splitlines()
    offenders = sorted({f for f in tracked for rx in _FORBIDDEN if rx.search(f)})
    assert offenders == [], f"forbidden paths tracked in git: {offenders}"


def test_data_dir_is_private_0700() -> None:
    data = _ROOT / "data"
    if not data.exists():
        pytest.skip("data/ not present on this checkout")
    mode = os.stat(data).st_mode & 0o777
    assert mode == 0o700, f"data/ must be 0700, found {oct(mode)}"


def test_index_dir_if_present_is_private_0700() -> None:
    idx = _ROOT / "data" / "index"
    if not idx.exists():
        pytest.skip("index not built on this checkout")
    mode = os.stat(idx).st_mode & 0o777
    assert mode == 0o700, f"data/index/ must be 0700, found {oct(mode)}"


#: Remotes Prax has explicitly sanctioned (R1 final review completed 2026-07-18;
#: push to the private repo authorized by Prax the same day). Anything else is
#: still an unsanctioned exfil target and must fail this guard.
_SANCTIONED_REMOTES = {"origin": "https://github.com/praxstack/dr-alex.git"}


def test_only_sanctioned_git_remotes() -> None:
    # R1 (post-review form): the history was purged of clinical data and reviewed
    # before any remote existed; now only the explicitly-sanctioned private
    # remote may be configured. New/changed remotes require Prax's consent.
    remotes = {name: _git("remote", "get-url", name).strip() for name in _git("remote").split()}
    assert remotes == _SANCTIONED_REMOTES, (
        f"R1 violation — unsanctioned git remote(s): {remotes} != {_SANCTIONED_REMOTES}"
    )



def _catches_broadly(handler) -> bool:
    """True if this handler swallows Exception/BaseException, or is a bare ``except:``.

    Handles the forms a line-regex misses: bare except, tuple handlers, and one-liners.
    """
    import ast

    def _is_broad(node) -> bool:
        return isinstance(node, ast.Name) and node.id in {"Exception", "BaseException"}

    if handler.type is None:  # bare `except:`
        return True
    if isinstance(handler.type, ast.Tuple):
        return any(_is_broad(e) for e in handler.type.elts)
    return _is_broad(handler.type)


def test_no_undocumented_silent_exception_handlers():
    """`except ...: pass` must be a deliberate, marked decision — never a default.

    A swallowed exception here is not a style issue: the handlers fixed in this pass were
    hiding a failed crash-recovery replay, an unwritten session-end stamp, dropped
    safety-audit lines, and lost mood records. Any new silent handler must carry
    SILENT-BY-DESIGN and a reason.

    Uses the AST rather than a regex, because the regex version missed one-liners
    (`except Exception: pass`), tuple handlers (`except (Exception, OSError):`),
    `BaseException`, and a `pass` preceded by a comment — and it only scanned ``dr_alex/``,
    leaving ``safety/`` (the package AGENTS.md names first) unguarded.
    """
    import ast

    offenders: list[str] = []
    for pkg in ("dr_alex", "safety"):
        root = _ROOT / pkg
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            src = path.read_text(encoding="utf-8")
            lines = src.splitlines()
            try:
                tree = ast.parse(src)
            except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if not all(isinstance(stmt, ast.Pass) for stmt in node.body):
                    continue
                # Only BROAD catches are the hazard. `except OSError: pass` around a chmod is a
                # legitimate, readable idiom; `except Exception: pass` is how a failed
                # crash-recovery replay went unnoticed. Marking the narrow ones too would just
                # devalue the marker.
                if not _catches_broadly(node):
                    continue
                # The marker may sit on the `except` line or anywhere in the handler body.
                span = lines[node.lineno - 1 : (node.end_lineno or node.lineno)]
                if any("SILENT-BY-DESIGN" in ln for ln in span):
                    continue
                offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno}")

    assert not offenders, (
        "silent exception handlers must log, or be marked SILENT-BY-DESIGN with a reason: "
        + ", ".join(offenders)
    )
