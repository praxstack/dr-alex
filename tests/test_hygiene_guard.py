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


def test_no_git_remote_before_final_review() -> None:
    # R1: privacy — ~/dr-alex must have no remote yet.
    remotes = _git("remote").split()
    assert remotes == [], f"R1 violation — unexpected git remote(s): {remotes}"
