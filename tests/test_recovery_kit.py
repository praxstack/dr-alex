"""Recovery using only synthetic keys, a temporary age identity, and a fresh key store."""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import keyring
import pytest

from dr_alex import cli, crypto, recovery_kit

STATE_KEY = base64.urlsafe_b64encode(bytes(range(32)))
KEYS = {
    "state-key": base64.b64encode(STATE_KEY).decode(),
    "pairing-key": base64.b64encode(bytes(reversed(range(32)))).decode(),
}
_FAKE_AGE_HEADER = b"age-encryption.org/v1\n"
_FAKE_IDENTITY = "SYNTHETIC-AGE-IDENTITY\n"
_FAKE_RECIPIENT = "age1" + "a" * 58
_NATIVE_AGE = shutil.which("age")
_NATIVE_AGE_KEYGEN = shutil.which("age-keygen")


def _fake_age_run(argv, *, input, **_kwargs):
    if "--encrypt" in argv:
        assert argv == ["age", "--encrypt", "--recipient", _FAKE_RECIPIENT]
        return subprocess.CompletedProcess(
            argv, 0, stdout=_FAKE_AGE_HEADER + base64.b64encode(input), stderr=b""
        )
    if "--decrypt" in argv:
        identity = argv[argv.index("--identity") + 1]
        if Path(identity).read_text(encoding="utf-8") != _FAKE_IDENTITY:
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"synthetic")
        try:
            plaintext = base64.b64decode(input.removeprefix(_FAKE_AGE_HEADER), validate=True)
        except (ValueError, UnicodeError):
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"synthetic")
        return subprocess.CompletedProcess(argv, 0, stdout=plaintext, stderr=b"")
    raise AssertionError(f"unexpected synthetic age argv: {argv}")


@pytest.fixture
def store(monkeypatch):
    values = dict(KEYS)
    crypto.reset_cache()
    monkeypatch.setattr(keyring, "get_password", lambda service, account: values.get(account))
    monkeypatch.setattr(
        keyring, "set_password", lambda service, account, value: values.update({account: value})
    )
    yield values
    crypto.reset_cache()


@pytest.fixture
def identity(tmp_path):
    target = tmp_path / "identity.txt"
    target.write_text(_FAKE_IDENTITY, encoding="utf-8")
    return target, _FAKE_RECIPIENT


@pytest.fixture
def native_identity(tmp_path):
    if _NATIVE_AGE is None or _NATIVE_AGE_KEYGEN is None:
        pytest.skip("native age and age-keygen unavailable; native integration skipped")
    target = tmp_path / "identity.txt"
    subprocess.run(
        [_NATIVE_AGE_KEYGEN, "-o", str(target)], capture_output=True, check=True, timeout=10
    )
    recipient = (
        subprocess.run(
            [_NATIVE_AGE_KEYGEN, "-y", str(target)], capture_output=True, check=True, timeout=10
        )
        .stdout.decode()
        .strip()
    )
    return target, recipient


@pytest.fixture(autouse=True)
def synthetic_age_boundary(monkeypatch, request):
    if "native_identity" not in request.fixturenames:
        monkeypatch.setattr(recovery_kit.subprocess, "run", _fake_age_run)


def _export(target, recipient):
    return cli.main(["recovery-kit", "export", "--recipient", recipient, "--output", str(target)])


def _restore(target, identity):
    return cli.main(
        ["recovery-kit", "restore", "--identity", str(identity), "--input", str(target)]
    )


@pytest.mark.parametrize("args", [["--encrypt"], ["--encrypt", "--recipient", "age1" + "b" * 58]])
def test_synthetic_age_rejects_missing_or_substituted_recipient(args):
    with pytest.raises(AssertionError):
        _fake_age_run(["age", *args], input=b"synthetic")


def test_public_recovery_kit_restores_archive_without_original_store(
    tmp_path, monkeypatch, store, native_identity
):
    monkeypatch.setattr(cli, "_print_oneshot", lambda text: 91)
    key_file, recipient = native_identity
    kit = tmp_path / "kit.age"
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w") as archive:
        member = tarfile.TarInfo("synthetic.txt")
        member.size = len(b"fixed synthetic backup content")
        archive.addfile(member, io.BytesIO(b"fixed synthetic backup content"))
    encrypted_archive = crypto.encrypt_bytes(content.getvalue())
    assert _export(kit, recipient) == 0
    assert kit.read_bytes().startswith(b"age-encryption.org/v1\n")
    assert stat.S_IMODE(kit.stat().st_mode) == 0o600
    assert all(value.encode() not in kit.read_bytes() for value in KEYS.values())

    store.clear()
    crypto.reset_cache()
    assert _restore(kit, key_file) == 0
    assert store == KEYS
    with tarfile.open(fileobj=io.BytesIO(crypto.decrypt_bytes(encrypted_archive))) as archive:
        assert archive.extractfile("synthetic.txt").read() == b"fixed synthetic backup content"
    assert _restore(kit, key_file) == 0
    assert store == KEYS


@pytest.mark.parametrize("failure", ["missing", "invalid", "existing", "symlink"])
def test_export_failure_never_creates_keys_or_overwrites_destination(
    tmp_path, store, identity, failure
):
    _, recipient = identity
    kit = tmp_path / "kit.age"
    if failure == "missing":
        store.pop("pairing-key")
    elif failure == "invalid":
        store["state-key"] = base64.b64encode(b"short").decode()
    elif failure == "existing":
        kit.write_bytes(b"preserve")
    else:
        kit.symlink_to(tmp_path / "absent")
    before = dict(store)
    assert _export(kit, recipient) == 1
    assert store == before
    if failure == "existing":
        assert kit.read_bytes() == b"preserve"
    elif failure == "symlink":
        assert kit.is_symlink() and not kit.exists()
    else:
        assert not kit.exists()
    assert not list(tmp_path.glob(".recovery-kit-*"))


@pytest.mark.parametrize("failure", ["wrong_identity", "corrupt", "conflict"])
def test_restore_failure_never_changes_destination_keys(tmp_path, store, identity, failure):
    key_file, recipient = identity
    kit = tmp_path / "kit.age"
    assert _export(kit, recipient) == 0
    store.clear()
    if failure == "wrong_identity":
        key_file = tmp_path / "wrong.txt"
        key_file.write_text("WRONG-SYNTHETIC-IDENTITY\n", encoding="utf-8")
    elif failure == "corrupt":
        kit.write_bytes(kit.read_bytes()[:-10])
    else:
        store["pairing-key"] = base64.b64encode(b"x" * 32).decode()
    before = dict(store)
    assert _restore(kit, key_file) == 1
    assert store == before


@pytest.mark.parametrize(
    "failure", ["version", "missing", "extra", "length", "base64", "duplicate"]
)
def test_invalid_decrypted_payload_is_rejected_before_any_key_write(
    tmp_path, store, identity, failure
):
    key_file, recipient = identity
    payload = {"version": 1, "service": "dr-alex", "secrets": dict(KEYS)}
    if failure == "version":
        payload["version"] = True
    elif failure == "missing":
        payload["secrets"].pop("pairing-key")
    elif failure == "extra":
        payload["secrets"]["unknown-key"] = "not allowed"
    elif failure == "length":
        payload["secrets"]["pairing-key"] = base64.b64encode(b"short").decode()
    elif failure == "base64":
        payload["secrets"]["state-key"] += "!"
    raw = json.dumps(payload)
    if failure == "duplicate":
        raw = raw.replace('"version": 1', '"version": 2, "version": 1')
    kit = tmp_path / "kit.age"
    encrypted = recovery_kit._age(["--encrypt", "--recipient", recipient], raw.encode())
    kit.write_bytes(encrypted)
    store.clear()
    assert _restore(kit, key_file) == 1
    assert store == {}


def test_partial_restore_retries_matching_keys_without_replacement(
    tmp_path, monkeypatch, store, identity
):
    key_file, recipient = identity
    kit = tmp_path / "kit.age"
    assert _export(kit, recipient) == 0
    store.clear()
    writes = []

    def fail_second(service, account, value):
        if writes:
            raise RuntimeError("SYNTHETIC_PRIVATE_ERROR")
        writes.append(account)
        store[account] = value

    monkeypatch.setattr(keyring, "set_password", fail_second)
    assert _restore(kit, key_file) == 1
    assert len(store) == 1
    accepted = dict(store)

    def resume(service, account, value):
        assert account not in accepted
        store[account] = value

    monkeypatch.setattr(keyring, "set_password", resume)
    assert _restore(kit, key_file) == 0
    assert store == KEYS


def test_export_publishes_only_complete_ciphertext_and_refuses_publication_race(
    tmp_path, monkeypatch, store, identity
):
    _, recipient = identity
    kit = tmp_path / "kit.age"
    real_link = os.link

    def raced_link(source, target):
        from pathlib import Path

        staged = Path(source).read_bytes()
        assert staged.startswith(b"age-encryption.org/v1\n")
        assert all(value.encode() not in staged for value in KEYS.values())
        assert stat.S_IMODE(Path(source).stat().st_mode) == 0o600
        kit.write_bytes(b"another owner")
        return real_link(source, target)

    monkeypatch.setattr(os, "link", raced_link)
    assert _export(kit, recipient) == 1
    assert kit.read_bytes() == b"another owner"
    assert not list(tmp_path.glob(".recovery-kit-*"))


@pytest.mark.parametrize("operation", ["export", "restore"])
def test_cli_errors_are_body_free_and_age_is_bounded(
    tmp_path, monkeypatch, store, identity, capsys, operation
):
    from dr_alex import recovery_kit

    key_file, recipient = identity
    kit = tmp_path / "kit.age"
    if operation == "restore":
        assert _export(kit, recipient) == 0

    def timeout(argv, **kwargs):
        assert argv[0] == "age"
        assert 0 < kwargs["timeout"] <= 30
        assert all(value not in str(argv) for value in KEYS.values())
        assert kwargs.get("input") is not None
        raise subprocess.TimeoutExpired(argv, 30, output=b"SYNTHETIC_PRIVATE_ERROR")

    monkeypatch.setattr(recovery_kit.subprocess, "run", timeout)
    assert (_export(kit, recipient) if operation == "export" else _restore(kit, key_file)) == 1
    captured = capsys.readouterr()
    assert "SYNTHETIC_PRIVATE_ERROR" not in captured.out + captured.err
    assert all(value not in captured.out + captured.err for value in KEYS.values())
    assert not list(tmp_path.glob(".recovery-kit-*"))


def test_cli_usage_never_echoes_unrecognized_argument(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_print_oneshot", lambda text: 91)
    assert cli.main(["recovery-kit", "SYNTHETIC_PRIVATE_ERROR"]) == 2
    assert "SYNTHETIC_PRIVATE_ERROR" not in capsys.readouterr().err


def test_export_fsync_failure_leaves_no_published_file(tmp_path, monkeypatch, store, identity):
    _, recipient = identity
    kit = tmp_path / "kit.age"

    def fail(fd):
        raise OSError("SYNTHETIC_PRIVATE_ERROR")

    monkeypatch.setattr(os, "fsync", fail)
    assert _export(kit, recipient) == 1
    assert not kit.exists()
    assert not list(tmp_path.glob(".recovery-kit-*"))


def test_invalid_recipient_is_rejected_before_key_read(monkeypatch, tmp_path, capsys):
    def fail(*args):
        raise AssertionError("key store should not be accessed")

    monkeypatch.setattr(keyring, "get_password", fail)
    assert _export(tmp_path / "kit.age", "SYNTHETIC_PRIVATE_ERROR") == 1
    assert "SYNTHETIC_PRIVATE_ERROR" not in capsys.readouterr().err


def test_conflict_appearing_during_restore_is_not_replaced(tmp_path, monkeypatch, store, identity):
    key_file, recipient = identity
    kit = tmp_path / "kit.age"
    assert _export(kit, recipient) == 0
    store.clear()
    reads = []

    def changed(service, account):
        reads.append(account)
        if len(reads) == 3:
            store[account] = "a different existing value"
        return store.get(account)

    monkeypatch.setattr(keyring, "get_password", changed)
    assert _restore(kit, key_file) == 1
    assert store == {"state-key": "a different existing value"}
