"""G19 durability backup: bundle create+verify, encrypted state.db snapshot, retention."""

from __future__ import annotations

import datetime as _dt
import subprocess

import pytest

from dr_alex import backup, crypto, statedb

_UTC = _dt.UTC


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


def test_backup_creates_verified_bundle_and_encrypted_snapshot(
    git_repo, tmp_path, monkeypatch
) -> None:
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
    # SQLite's backup API changes internal page counters. Verify all schema/data
    # rather than requiring the old unsafe raw-file-copy representation.
    import sqlite3

    restored_db = tmp_path / "restored.db"
    restored_db.write_bytes(restored)
    with sqlite3.connect(db) as original, sqlite3.connect(restored_db) as recovered:
        assert list(recovered.iterdump()) == list(original.iterdump())
        assert recovered.execute("PRAGMA integrity_check").fetchone() == ("ok",)


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
    # Retention only advances after verification; seed valid historical bundles.
    seed = git_repo.parent / "seed.bundle"
    assert backup._run_git(git_repo, "bundle", "create", str(seed), "--all").returncode == 0
    for i in range(14):
        ts = f"202601{i:02d}T000000Z"
        (dest / f"{ts}-dr-alex.bundle").write_bytes(seed.read_bytes())
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


def test_backup_includes_committed_wal_rows(git_repo, tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "wal.db"
    monkeypatch.setenv("DR_ALEX_STATE_DB", str(db))
    with sqlite3.connect(db) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE evidence (value TEXT)")
        live.execute("INSERT INTO evidence VALUES (?)", ("committed Unicode नमस्ते",))
        live.commit()
        result = backup.run_backup(repo=git_repo)
        assert result.ok, result.errors
        restored = tmp_path / "restored.db"
        from pathlib import Path

        restored.write_bytes(crypto.decrypt_bytes(Path(result.snapshot_path).read_bytes()))
        with sqlite3.connect(restored) as recovered:
            assert recovered.execute("SELECT value FROM evidence").fetchall() == [
                ("committed Unicode नमस्ते",)
            ]


def test_backup_preserves_private_recovery_files(git_repo, tmp_path, monkeypatch):
    import io
    import tarfile
    from pathlib import Path

    repo = git_repo
    data = repo / "data"
    data.mkdir(exist_ok=True)
    (data / "continuity.md").write_text("SYNTHETIC continuity")
    (data / "session_state.json").write_text('{"pending": "synthetic"}')
    records = tmp_path / "private-records"
    records.mkdir()
    (records / "Active-File.md").write_text("SYNTHETIC active record")
    monkeypatch.setenv("DR_ALEX_RECORDS_DIR", str(records))
    monkeypatch.setenv("DR_ALEX_ACTIVE_FILE", str(records / "Active-File.md"))
    result = backup.run_backup(repo=repo)
    assert result.ok, result.errors
    archive = crypto.decrypt_bytes(Path(result.private_archive_path).read_bytes())
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        assert tar.extractfile("data/continuity.md").read() == b"SYNTHETIC continuity"
        assert tar.extractfile("data/session_state.json").read() == b'{"pending": "synthetic"}'
        assert tar.extractfile("records/Active-File.md").read() == b"SYNTHETIC active record"
        assert not any("/backups/" in name or name.endswith(".pid") for name in tar.getnames())


def test_failed_generation_preserves_good_retention(git_repo, monkeypatch):
    from pathlib import Path

    dest = backup.backups_dir(git_repo)
    for i in range(backup.RETENTION):
        (dest / f"202501{i:02d}-dr-alex.bundle").write_bytes(b"old-good-bundle")
    before = {p.name for p in dest.iterdir()}

    def git_result(repo, *args):
        if args[:2] == ("bundle", "create"):
            Path(args[2]).write_bytes(b"new-bundle")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(backup, "_run_git", git_result)
    monkeypatch.setattr(
        backup.crypto,
        "encrypt_bytes",
        lambda *a: (_ for _ in ()).throw(crypto.CryptoError("synthetic")),
    )
    result = backup.run_backup(repo=git_repo)
    assert not result.ok
    assert before <= {p.name for p in dest.iterdir()}
    assert result.pruned == 0


def test_private_snapshot_excludes_journal_and_copies_active_symlink(
    git_repo, tmp_path, monkeypatch
):
    import io
    import tarfile
    from pathlib import Path

    data = git_repo / "data"
    data.mkdir(exist_ok=True)
    (data / "state.db-journal").write_bytes(b"STALE_JOURNAL")
    records = tmp_path / "records"
    records.mkdir()
    original = tmp_path / "real-active.md"
    original.write_text("SYNTHETIC linked content")
    active = records / "Active-File.md"
    active.symlink_to(original)
    monkeypatch.setenv("DR_ALEX_RECORDS_DIR", str(records))
    monkeypatch.setenv("DR_ALEX_ACTIVE_FILE", str(active))
    result = backup.run_backup(repo=git_repo)
    assert result.ok, result.errors
    with tarfile.open(
        fileobj=io.BytesIO(crypto.decrypt_bytes(Path(result.private_archive_path).read_bytes())),
        mode="r:gz",
    ) as archive:
        assert "data/state.db-journal" not in archive.getnames()
        member = archive.getmember("records/Active-File.md")
        assert member.isfile() and not member.issym()
        assert archive.extractfile(member).read() == b"SYNTHETIC linked content"


def test_backup_restores_configured_hermes_commits_from_live_wal(
    git_repo, tmp_path, monkeypatch, capsys
):
    import hashlib
    import io
    import json
    import sqlite3
    import tarfile
    from pathlib import Path

    hermes = tmp_path / "therapist" / "history.db"
    hermes.parent.mkdir()
    (hermes.parent / "credentials.env").write_text("SYNTHETIC_CREDENTIAL")
    monkeypatch.setenv("DR_ALEX_HERMES_DB", str(hermes))
    message = "\t नमस्ते café 🌿\n  exact whitespace \t"
    with sqlite3.connect(hermes) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
        live.commit()
        live.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fixture setup only
        live.execute("INSERT INTO messages (content) VALUES (?)", (message,))
        live.commit()
        with sqlite3.connect(hermes.as_uri() + "?mode=ro&immutable=1", uri=True) as main_only:
            assert main_only.execute("SELECT count(*) FROM messages").fetchone() == (0,)
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (hermes, Path(str(hermes) + "-wal"))
        }
        result = backup.run_backup(repo=git_repo)
        assert result.ok, result.errors
        envelope = Path(result.private_archive_path).read_bytes()
        assert message.encode() not in envelope
        with tarfile.open(
            fileobj=io.BytesIO(crypto.decrypt_bytes(envelope)), mode="r:gz"
        ) as archive:
            assert "hermes/state.db" in archive.getnames()
            assert not any(
                "credentials" in name or name.endswith(("-wal", "-shm"))
                for name in archive.getnames()
            )
            restored = tmp_path / "restored-hermes.db"
            restored.write_bytes(archive.extractfile("hermes/state.db").read())
            manifest = json.load(archive.extractfile("recovery-manifest.json"))
            assert manifest["coverage"]["hermes_history"] == {
                "status": "included",
                "source": str(hermes),
                "member": "hermes/state.db",
            }
        with sqlite3.connect(restored) as recovered:
            assert recovered.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert recovered.execute("SELECT content FROM messages ORDER BY id").fetchall() == [
                (message,)
            ]
        assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    captured = capsys.readouterr()
    assert message not in captured.out + captured.err
    assert "SYNTHETIC_CREDENTIAL" not in captured.out + captured.err


def test_missing_optional_hermes_is_explicit_in_encrypted_coverage(git_repo):
    import io
    import json
    import tarfile
    from pathlib import Path

    from dr_alex import history_recall

    result = backup.run_backup(repo=git_repo)
    assert result.ok, result.errors
    with tarfile.open(
        fileobj=io.BytesIO(crypto.decrypt_bytes(Path(result.private_archive_path).read_bytes())),
        mode="r:gz",
    ) as archive:
        assert "hermes/state.db" not in archive.getnames()
        manifest = json.load(archive.extractfile("recovery-manifest.json"))
        assert manifest["coverage"]["hermes_history"] == {
            "status": "missing-optional",
            "source": str(history_recall.db_path()),
            "member": None,
        }


@pytest.mark.parametrize("failure", ["missing", "corrupt", "empty", "unreadable", "busy"])
def test_invalid_hermes_generation_preserves_prior_artifacts(
    failure, git_repo, tmp_path, monkeypatch, capsys
):
    import sqlite3
    import time

    previous = backup.run_backup(repo=git_repo)
    assert previous.ok, previous.errors
    dest = git_repo / "data" / "backups"
    before = {p.name: p.read_bytes() for p in dest.iterdir()}
    hermes = tmp_path / "hermes-failure.db"
    monkeypatch.setenv("DR_ALEX_HERMES_DB", str(hermes))
    monkeypatch.setattr(backup, "SNAPSHOT_TIMEOUT_SECONDS", 0.1)
    locked = None
    if failure == "corrupt":
        hermes.write_bytes(b"SYNTHETIC_PRIVATE_DATABASE_BODY")
    elif failure == "empty":
        hermes.touch()
    elif failure in ("unreadable", "busy"):
        locked = sqlite3.connect(hermes)
        locked.execute("CREATE TABLE messages (content TEXT)")
        locked.commit()
        if failure == "unreadable":
            locked.close()
            locked = None
            real_connect = sqlite3.connect
            source_uri = hermes.resolve().as_uri()

            def unreadable_source(database, *args, **kwargs):
                if str(database).startswith(source_uri):
                    raise PermissionError("synthetic unreadable SQLite source")
                return real_connect(database, *args, **kwargs)

            monkeypatch.setattr(sqlite3, "connect", unreadable_source)
        else:
            locked.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        result = backup.run_backup(repo=git_repo)
        assert time.monotonic() - started < 3
        assert not result.ok and not result.verified
        assert result.pruned == 0
        assert result.bundle_path is None and result.private_archive_path is None
        assert before == {p.name: p.read_bytes() for p in dest.iterdir()}
        captured = capsys.readouterr()
        assert "SYNTHETIC_PRIVATE_DATABASE_BODY" not in captured.out + captured.err + str(
            result.errors
        )
        if failure == "busy":
            assert any("TimeoutError" in error for error in result.errors)
    finally:
        if locked is not None:
            locked.close()


def test_private_sqlite_uses_same_deadline_as_hermes(git_repo, tmp_path, monkeypatch):
    import sqlite3
    import time

    data = git_repo / "data"
    data.mkdir()
    db = data / "private.sqlite"
    with sqlite3.connect(db) as live:
        live.execute("CREATE TABLE pending (body TEXT)")
        live.commit()
        live.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(backup, "SNAPSHOT_TIMEOUT_SECONDS", 0.1)
        started = time.monotonic()
        result = backup.run_backup(repo=git_repo)
        assert time.monotonic() - started < 3
        assert not result.ok
        assert any("TimeoutError" in error for error in result.errors)
        assert not list((data / "backups").glob("*-dr-alex.bundle"))


def test_snapshot_rejects_readable_sqlite_with_broken_index(tmp_path):
    import sqlite3

    db = tmp_path / "broken-index.db"
    with sqlite3.connect(db) as source:
        source.execute("CREATE TABLE messages (body TEXT)")
        source.execute("CREATE INDEX by_body ON messages(body)")
        source.execute("INSERT INTO messages VALUES ('synthetic')")
        source.commit()
        # A structurally readable database can still fail integrity_check.
        root = source.execute("SELECT rootpage FROM sqlite_master WHERE name='by_body'").fetchone()[
            0
        ]
        page_size = source.execute("PRAGMA page_size").fetchone()[0]
    raw = bytearray(db.read_bytes())
    raw[(root - 1) * page_size + 3 : (root - 1) * page_size + 5] = b"\x00\x00"
    db.write_bytes(raw)
    with pytest.raises(sqlite3.DatabaseError, match="integrity check failed"):
        backup._snapshot_sqlite(db, tmp_path / "snapshot.db")
