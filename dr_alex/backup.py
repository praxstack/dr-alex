"""G19 durability backups — ``dr-alex backup`` (born from a real uv-sync data-loss incident).

One command produces two durable artifacts under ``data/backups/`` (dir 0700, gitignored):

  1. a ``git bundle --all`` of the whole repo (every ref, self-contained, offline-restorable),
  2. a mode-0600 **encrypted** snapshot of ``state.db`` (Fernet, whole file — the telemetry
     that isn't in git).

Every retained bundle is verified (``git bundle verify``); a 14-bundle retention window prunes
the oldest. On success it is **silent** (returns a result, prints nothing). It NEVER runs
``git add -A`` / commits / pushes — it only *reads* the repo into a bundle.

This module owns exactly one subprocess site (``_run_git``); it never touches the model.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dr_alex import crypto, statedb

_log = logging.getLogger("dr_alex.backup")

RETENTION = 14  # keep the 14 most-recent bundles (+ their state.db snapshots)


@dataclass
class BackupResult:
    ok: bool
    bundle_path: str | None = None
    snapshot_path: str | None = None
    verified: bool = False
    pruned: int = 0
    errors: list[str] = field(default_factory=list)


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """The sole subprocess site here — runs read-only ``git`` in ``repo``. Never the model."""
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["git", "-C", str(repo), *args],
        capture_output=True, timeout=120,
    )


def repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default: this module) to the dir containing ``.git``."""
    here = (start or Path(__file__).resolve()).parent
    for cand in (here, *here.parents):
        if (cand / ".git").exists():
            return cand
    return None


def backups_dir(repo: Path) -> Path:
    d = repo / "data" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _ts(now: _dt.datetime | None) -> str:
    dt = now or _dt.datetime.now(_dt.UTC)
    dt = dt.astimezone(_dt.UTC) if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _prune(dest: Path, errors: list[str]) -> int:
    """Keep the newest ``RETENTION`` bundles; drop older bundles + their snapshots."""
    bundles = sorted(dest.glob("*-dr-alex.bundle"))
    pruned = 0
    for old in bundles[:-RETENTION] if len(bundles) > RETENTION else []:
        stem = old.name[: -len("-dr-alex.bundle")]
        for f in (old, dest / f"{stem}-state.db.enc"):
            try:
                if f.exists():
                    f.unlink()
                    pruned += 1
            except OSError as exc:
                errors.append(f"prune {f.name}: {type(exc).__name__}")
    return pruned


def run_backup(*, now: _dt.datetime | None = None, repo: Path | None = None) -> BackupResult:
    """Create + verify a bundle and an encrypted state.db snapshot; prune to 14. Never raises."""
    repo = repo or repo_root()
    if repo is None:
        return BackupResult(ok=False, errors=["no git repo found (backup needs the repo root)"])

    errors: list[str] = []
    dest = backups_dir(repo)
    ts = _ts(now)
    bundle = dest / f"{ts}-dr-alex.bundle"

    # 1. git bundle --all (read-only; NEVER add/commit/push).
    try:
        proc = _run_git(repo, "bundle", "create", str(bundle), "--all")
        if proc.returncode != 0:
            return BackupResult(ok=False, errors=[f"git bundle failed: exit {proc.returncode}"])
    except (OSError, subprocess.SubprocessError) as exc:
        return BackupResult(ok=False, errors=[f"git bundle spawn failed: {type(exc).__name__}"])

    # 2. Verify EVERY retained bundle (the new one plus survivors).
    verified = True
    for b in sorted(dest.glob("*-dr-alex.bundle")):
        try:
            v = _run_git(repo, "bundle", "verify", str(b))
            if v.returncode != 0:
                verified = False
                errors.append(f"verify {b.name}: exit {v.returncode}")
        except (OSError, subprocess.SubprocessError) as exc:
            verified = False
            errors.append(f"verify {b.name}: {type(exc).__name__}")

    # 3. Encrypted whole-file snapshot of state.db (skip cleanly if there's no db yet).
    snapshot_path: str | None = None
    db = statedb.state_db_path()
    if db.exists():
        snap = dest / f"{ts}-state.db.enc"
        try:
            snap.write_bytes(crypto.encrypt_bytes(db.read_bytes()))
            os.chmod(snap, 0o600)
            snapshot_path = str(snap)
        except (OSError, crypto.CryptoError) as exc:
            errors.append(f"state.db snapshot failed: {type(exc).__name__}")

    pruned = _prune(dest, errors)
    ok = verified and not errors
    return BackupResult(
        ok=ok, bundle_path=str(bundle), snapshot_path=snapshot_path,
        verified=verified, pruned=pruned, errors=errors,
    )
