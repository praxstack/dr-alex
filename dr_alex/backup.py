"""G19 durability backups — ``dr-alex backup`` (born from a real uv-sync data-loss incident).

One command produces three durable artifacts under ``data/backups/`` (dir 0700, gitignored):

  1. a ``git bundle --all`` of the whole repo (every ref, self-contained, offline-restorable),
  2. a mode-0600 **encrypted** snapshot of ``state.db`` (Fernet, whole file — the telemetry
     that isn't in git),
  3. an encrypted tar of private data and records, including a recovery path manifest.

Every retained bundle is verified (``git bundle verify``); a 14-bundle retention window prunes
the oldest. On success it is **silent** (returns a result, prints nothing). It NEVER runs
``git add -A`` / commits / pushes — it only *reads* the repo into a bundle.

This module owns exactly one subprocess site (``_run_git``); it never touches the model.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import logging
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from dr_alex import config, crypto, history_recall, statedb

_log = logging.getLogger("dr_alex.backup")

RETENTION = 14  # keep the 14 most-recent bundles (+ their state.db snapshots)
SNAPSHOT_TIMEOUT_SECONDS = 30.0


@dataclass
class BackupResult:
    ok: bool
    bundle_path: str | None = None
    snapshot_path: str | None = None
    private_archive_path: str | None = None
    verified: bool = False
    pruned: int = 0
    errors: list[str] = field(default_factory=list)


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """The sole subprocess site here — runs read-only ``git`` in ``repo``. Never the model."""
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["git", "-C", str(repo), *args],
        capture_output=True,
        timeout=120,
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
    os.chmod(d, 0o700)
    return d


def _ts(now: _dt.datetime | None) -> str:
    dt = now or _dt.datetime.now(_dt.UTC)
    dt = dt.astimezone(_dt.UTC) if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)
    return dt.strftime("%Y%m%dT%H%M%S%fZ")


def _prune(dest: Path, errors: list[str]) -> int:
    """Keep the newest ``RETENTION`` bundles; drop older bundles + their snapshots."""
    bundles = sorted(dest.glob("*-dr-alex.bundle"))
    pruned = 0
    for old in bundles[:-RETENTION] if len(bundles) > RETENTION else []:
        stem = old.name[: -len("-dr-alex.bundle")]
        for f in (old, dest / f"{stem}-state.db.enc", dest / f"{stem}-private.tar.gz.enc"):
            try:
                if f.exists():
                    f.unlink()
                    pruned += 1
            except OSError as exc:
                errors.append(f"prune {f.name}: {type(exc).__name__}")
    return pruned


def _snapshot_sqlite(db: Path, snapshot: Path) -> None:
    """Copy committed pages read-only, with a deadline shared by backup and validation."""
    deadline = time.monotonic() + SNAPSHOT_TIMEOUT_SECONDS

    def check_deadline(*_progress: int) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite snapshot deadline exceeded")

    if db.stat().st_size == 0:
        raise sqlite3.DatabaseError("empty SQLite source")
    snapshot.unlink(missing_ok=True)
    with (
        closing(
            sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)
        ) as source,
        closing(sqlite3.connect(snapshot, timeout=0.05)) as target,
    ):
        check_deadline()
        source.backup(target, pages=256, progress=check_deadline, sleep=0.05)
        check_deadline()
        target.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("SQLite snapshot integrity check failed")
        check_deadline()


def run_backup(*, now: _dt.datetime | None = None, repo: Path | None = None) -> BackupResult:
    """Create + verify a bundle and an encrypted state.db snapshot; prune to 14. Never raises."""
    repo = repo or repo_root()
    if repo is None:
        return BackupResult(ok=False, errors=["no git repo found (backup needs the repo root)"])

    errors: list[str] = []
    try:
        dest = backups_dir(repo)
    except OSError:
        return BackupResult(ok=False, errors=["backup directory unavailable or not private"])
    ts = _ts(now)
    bundle = dest / f"{ts}-dr-alex.bundle"

    # Publish only a verified bundle; interrupted creation cannot poison later runs.
    staged = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".bundle-", dir=dest, delete=False) as temporary:
            staged = Path(temporary.name)
        proc = _run_git(repo, "bundle", "create", str(staged), "--all")
        if proc.returncode != 0:
            return BackupResult(ok=False, errors=[f"git bundle failed: exit {proc.returncode}"])
        check = _run_git(repo, "bundle", "verify", str(staged))
        if check.returncode != 0:
            return BackupResult(ok=False, errors=["new git bundle verification failed"])
        staged.chmod(0o600)
        os.replace(staged, bundle)
    except (OSError, subprocess.SubprocessError) as exc:
        return BackupResult(ok=False, errors=[f"git bundle failed: {type(exc).__name__}"])
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)

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
            with tempfile.TemporaryDirectory(prefix="dr-alex-snapshot-") as tmp:
                consistent = Path(tmp) / "state.db"
                _snapshot_sqlite(db, consistent)
                snap.write_bytes(crypto.encrypt_bytes(consistent.read_bytes()))
            os.chmod(snap, 0o600)
            snapshot_path = str(snap)
        except (OSError, sqlite3.Error, crypto.CryptoError) as exc:
            errors.append(f"state.db snapshot failed: {type(exc).__name__}")

    # Include ignored continuity, pending fanout, books and records. SQLite files
    # get online snapshots too; WAL/SHM sidecars and live pidfiles are not restores.
    private_archive_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="dr-alex-private-") as tmp:
            contents = io.BytesIO()
            with tarfile.open(fileobj=contents, mode="w:gz") as archive:
                roots = [(repo / "data", "data"), (config.records_dir(), "records")]
                added = set()
                for root, prefix in roots:
                    if not root.exists():
                        continue
                    for file in sorted(root.rglob("*")):
                        relative = file.relative_to(root)
                        if (
                            not file.is_file()
                            or file.is_symlink()
                            or any(part == "backups" for part in relative.parts)
                            or file.name.endswith(("-wal", "-shm", "-journal", ".pid", ".tmp"))
                        ):
                            continue
                        name = f"{prefix}/{relative.as_posix()}"
                        candidate = file
                        if file.suffix in (".db", ".sqlite", ".sqlite3"):
                            candidate = Path(tmp) / "snapshot.db"
                            _snapshot_sqlite(file, candidate)
                        archive.add(candidate, arcname=name, recursive=False)
                        added.add(file.resolve())
                active = config.active_file_path()
                if active.is_file() and active.resolve() not in added:
                    archive.add(active.resolve(), arcname="records/Active-File.md", recursive=False)
                hermes = history_recall.db_path()
                hermes_coverage = {
                    "status": "missing-optional",
                    "source": str(hermes.resolve()),
                    "member": None,
                }
                try:
                    hermes.stat()
                except FileNotFoundError:
                    if history_recall.HERMES_DB_ENV in os.environ:
                        raise
                else:
                    consistent = Path(tmp) / "hermes.db"
                    _snapshot_sqlite(hermes, consistent)
                    archive.add(consistent, arcname="hermes/state.db", recursive=False)
                    hermes_coverage.update(status="included", member="hermes/state.db")
                manifest = json.dumps(
                    {
                        "version": 1,
                        "created_at": ts,
                        "coverage": {"hermes_history": hermes_coverage},
                        "repo": str(repo.resolve()),
                        "state_db": str(db.resolve()),
                        "records_dir": str(config.records_dir().resolve()),
                        "active_file": str(active.resolve()),
                        "key_required": "macOS Keychain service dr-alex; state-key and pairing-key",
                    }
                ).encode()
                info = tarfile.TarInfo("recovery-manifest.json")
                info.size, info.mode = len(manifest), 0o600
                archive.addfile(info, io.BytesIO(manifest))
            target = dest / f"{ts}-private.tar.gz.enc"
            target.write_bytes(crypto.encrypt_bytes(contents.getvalue()))
            target.chmod(0o600)
            # Verify the encrypted envelope and tar directory before reporting success.
            with tarfile.open(
                fileobj=io.BytesIO(crypto.decrypt_bytes(target.read_bytes())), mode="r:gz"
            ) as archive:
                archive.getmembers()
            private_archive_path = str(target)
    except (OSError, sqlite3.Error, crypto.CryptoError, tarfile.TarError) as exc:
        errors.append(f"private archive failed: {type(exc).__name__}")

    # A failed generation must never evict a complete recovery generation.
    if not verified or errors:
        for candidate in (bundle, dest / f"{ts}-state.db.enc", dest / f"{ts}-private.tar.gz.enc"):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                errors.append("incomplete artifact cleanup failed")
        return BackupResult(ok=False, verified=False, errors=errors)
    pruned = _prune(dest, errors)
    ok = not errors
    return BackupResult(
        ok=ok,
        bundle_path=str(bundle),
        snapshot_path=snapshot_path,
        private_archive_path=private_archive_path,
        verified=verified,
        pruned=pruned,
        errors=errors,
    )
