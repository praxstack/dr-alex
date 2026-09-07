"""Explicit age-encrypted escrow of the two keys required by the backup manifest.

Only ciphertext is staged on disk. Run restore with Dr. Alex stopped: keyring has no
cross-process compare-and-set API. Existing values are checked before every write and a
partially completed restore can be retried. The runtime Keychain remains the key owner.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import keyring

from dr_alex import crypto
from dr_alex.atomicio import _fsync_dir
from dr_alex.pairing import PAIRING_KEY_ACCOUNT

_ACCOUNTS = (crypto.STATE_KEY_ACCOUNT, PAIRING_KEY_ACCOUNT)
_MAX_KIT_BYTES = 16384
_AGE_TIMEOUT = 30


class RecoveryKitError(RuntimeError):
    """A bounded, body-free recovery failure safe to display in the CLI."""


def _validate(payload: object) -> dict[str, str]:
    try:
        if (
            not isinstance(payload, dict)
            or set(payload) != {"version", "service", "secrets"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
            or payload["service"] != crypto.SERVICE
            or not isinstance(payload["secrets"], dict)
            or set(payload["secrets"]) != set(_ACCOUNTS)
        ):
            raise ValueError
        for account, value in payload["secrets"].items():
            if not isinstance(value, str):
                raise ValueError
            secret = base64.b64decode(value, validate=True)
            if base64.b64encode(secret).decode("ascii") != value:
                raise ValueError
            if account == crypto.STATE_KEY_ACCOUNT:
                decoded = base64.b64decode(secret, altchars=b"-_", validate=True)
                if len(decoded) != 32 or base64.urlsafe_b64encode(decoded) != secret:
                    raise ValueError
            elif len(secret) != 32:
                raise ValueError
        return payload["secrets"]
    except (TypeError, ValueError, KeyError):
        raise RecoveryKitError("InvalidKit: required keys or schema are invalid.") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise RecoveryKitError("InvalidKit: duplicate fields are not accepted.")
        result[name] = value
    return result


def _age(args: list[str], data: bytes) -> bytes:
    try:
        result = subprocess.run(
            ["age", *args],
            input=data,
            capture_output=True,
            timeout=_AGE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        raise RecoveryKitError(
            "AgeFailed: check age installation and identity access; retry."
        ) from None
    if result.returncode != 0:
        raise RecoveryKitError("AgeFailed: check the recipient, identity, and kit integrity.")
    return result.stdout


def export_kit(recipient: str, destination: Path) -> None:
    """Read existing keys directly from Keychain and publish ciphertext without overwrite."""
    try:
        # Native age recipients avoid plugin execution or accidentally accepting private keys.
        if re.fullmatch(r"age1[0-9a-z]{58}", recipient) is None:
            raise RecoveryKitError("InvalidRecipient: supply an age-keygen public recipient.")
        if os.path.lexists(destination):
            raise RecoveryKitError("DestinationExists: choose a new output filename.")
        payload = {
            "version": 1,
            "service": crypto.SERVICE,
            "secrets": {
                account: keyring.get_password(crypto.SERVICE, account) for account in _ACCOUNTS
            },
        }
        _validate(payload)  # Missing keys are an error; never mint a replacement for export.
        ciphertext = _age(["--encrypt", "--recipient", recipient], json.dumps(payload).encode())
        if not ciphertext.startswith(b"age-encryption.org/v1\n"):
            raise RecoveryKitError("AgeFailed: encrypted output was not produced.")
        # The shared atomic writer replaces existing files; a hard link provides atomic
        # create-only publication, including when another writer wins after our early check.
        # ponytail: requires hard-link support; use a platform exclusive rename if needed.
        with tempfile.NamedTemporaryFile(prefix=".recovery-kit-", dir=destination.parent) as staged:
            staged.write(ciphertext)
            staged.flush()
            os.fsync(staged.fileno())
            os.link(staged.name, destination)
            _fsync_dir(destination.parent)
    except RecoveryKitError:
        raise
    except Exception:  # noqa: BLE001 — Keychain/filesystem error bodies may contain secrets
        raise RecoveryKitError(
            "ExportFailed: check Keychain and destination access; retry."
        ) from None


def restore_kit(source: Path, identity: Path) -> None:
    """Validate all keys and conflicts before writing; safely resume matching partial restores."""
    try:
        if not source.is_file():
            raise RecoveryKitError("InvalidKit: supply an encrypted kit file.")
        with source.open("rb") as file:
            ciphertext = file.read(_MAX_KIT_BYTES + 1)
        if len(ciphertext) > _MAX_KIT_BYTES:
            raise RecoveryKitError("InvalidKit: recovery kit exceeds the size limit.")
        plaintext = _age(["--decrypt", "--identity", str(identity)], ciphertext)
        secrets = _validate(json.loads(plaintext, object_pairs_hook=_unique_object))
        # Share the runtime loader's in-process lock. Keep Dr. Alex stopped during restore
        # because the portable keyring API cannot exclude writers in other processes.
        with crypto._lock:
            for account in _ACCOUNTS:
                existing = keyring.get_password(crypto.SERVICE, account)
                if existing is not None and not hmac.compare_digest(existing, secrets[account]):
                    raise RecoveryKitError(
                        "KeyConflict: an existing key differs; use a fresh key store."
                    )
            for account in _ACCOUNTS:
                existing = keyring.get_password(crypto.SERVICE, account)
                if existing is not None:
                    if not hmac.compare_digest(existing, secrets[account]):
                        raise RecoveryKitError(
                            "KeyConflict: an existing key changed; stop and inspect."
                        )
                    continue
                keyring.set_password(crypto.SERVICE, account, secrets[account])
    except RecoveryKitError:
        raise
    except Exception:  # noqa: BLE001 — suppress decrypted JSON and Keychain exception bodies
        raise RecoveryKitError(
            "RestoreFailed: check kit, identity and Keychain access; retry safely."
        ) from None
    finally:
        crypto.reset_cache()


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's default error message echoes unknown arguments, which may be private.
        raise _UsageError


def main(args: list[str]) -> int:
    parser = _Parser(prog="dr-alex recovery-kit")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser(
        "export", help="export existing keys to an independent age recipient"
    )
    export.add_argument("--recipient", required=True)
    export.add_argument("--output", required=True, type=Path)
    restore = commands.add_parser("restore", help="restore keys with Dr. Alex stopped")
    restore.add_argument("--identity", required=True, type=Path)
    restore.add_argument("--input", required=True, type=Path)
    try:
        options = parser.parse_args(args)
    except _UsageError:
        print(
            "UsageError: use recovery-kit export or restore --help for required options.",
            file=sys.stderr,
        )
        return 2
    except SystemExit as exc:  # --help
        return int(exc.code)
    try:
        if options.command == "export":
            export_kit(options.recipient, options.output)
            print("Recovery kit exported. Keep the independent age identity separate.")
        else:
            restore_kit(options.input, options.identity)
            print("Recovery keys restored. Restart Dr. Alex before using the restored backup.")
    except RecoveryKitError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
