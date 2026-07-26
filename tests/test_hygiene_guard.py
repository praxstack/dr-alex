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
    re.compile(r"^data/\.(checkin|health|continuity)\.[^/]*\.tmp$"),  # atomic-write temps
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
