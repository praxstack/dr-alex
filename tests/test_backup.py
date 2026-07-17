"""G19 durability backup: bundle create+verify, encrypted state.db snapshot, retention."""

from __future__ import annotations

import datetime as _dt
import subprocess

import pytest

from dr_alex import backup, crypto, statedb

_UTC = _dt.timezone.utc


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("dr-alex\n")
    _git(root, "add", "README.md")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "init")
    return root


def test_backup_creates_verified_bundle_and_encrypted_snapshot(git_repo, tmp_path, monkeypatch) -> None:
    # A real state.db to snapshot.
    db = tmp_path / "state.db"
    monkeypatch.setenv("DR_ALEX_STATE_DB", str(db))
    statedb.add_homework("SECRET_BACKUP_TITLE", path=db)

    res = backup.run_backup(repo=git_repo)
    assert res.ok, res.errors
    assert res.verified is True

    bundle = list((git_repo / "data" / "backups").glob("*-dr-alex.bundle"))
    snapshot = list((git_repo / "data" / "backups").glob("*-state.db.enc"))
    assert len(bundle) == 1 and len(snapshot) == 1

    # The snapshot is encrypted at rest (plaintext title absent) but decryptable.
    raw = snapshot[0].read_bytes()
    assert b"SECRET_BACKUP_TITLE" not in raw
    restored = crypto.decrypt_bytes(raw)
    assert restored == db.read_bytes()


def test_backup_never_runs_git_add(git_repo, monkeypatch) -> None:
    seen = []
    real = backup._run_git

    def spy(repo, *args):
        seen.append(args)
        return real(repo, *args)

    monkeypatch.setattr(backup, "_run_git", spy)
    backup.run_backup(repo=git_repo)
    # Only read-only bundle subcommands — never add/commit/push.
    verbs = {a[0] for a in seen}
    assert verbs <= {"bundle"}
    assert not any("add" in a or "commit" in a or "push" in a for a in seen)


def test_retention_keeps_14(git_repo, monkeypatch) -> None:
    dest = backup.backups_dir(git_repo)
    # Pre-seed 14 old bundles (+ snapshots) with older timestamps.
    for i in range(14):
        ts = f"202601{i:02d}T000000Z"
        (dest / f"{ts}-dr-alex.bundle").write_bytes(b"old")
        (dest / f"{ts}-state.db.enc").write_bytes(b"old")

    # A fresh backup makes 15; retention prunes back to 14.
    res = backup.run_backup(repo=git_repo, now=_dt.datetime(2026, 7, 18, tzinfo=_UTC))
    remaining = sorted((dest).glob("*-dr-alex.bundle"))
    assert len(remaining) == 14
    assert res.pruned >= 1
    # The oldest pre-seeded bundle is gone.
    assert not (dest / "20260100T000000Z-dr-alex.bundle").exists()


def test_no_repo_is_reported(monkeypatch, tmp_path) -> None:
    # repo_root returns None when there's no .git anywhere up the tree.
    monkeypatch.setattr(backup, "repo_root", lambda start=None: None)
    res = backup.run_backup()
    assert res.ok is False
    assert res.errors
