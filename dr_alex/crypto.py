"""App-layer encryption for ``state.db`` free-text columns (council D2).

Council ruling D2 inverted the encryption rule to a **plaintext allowlist**: only
ints/floats, enums, timestamps, ULIDs/ids, booleans, and counts may sit in the clear.
*Every* free-text column — transcript bodies, the continuity cache, homework titles,
key_insight, thread titles, notes — is Fernet-encrypted at the application layer before a
byte ever reaches SQLite. Because the ciphertext is produced here, no plaintext therapy
content is present in ``state.db`` (or any of its journal/WAL files) at rest, regardless of
SQLite's storage internals.

Key management (council D2, binding):
  - The key is ``secrets.token_bytes(32)`` (base64-url-encoded for Fernet).
  - It lives in the macOS Keychain via the python ``keyring`` (Security framework) backend,
    under service ``"dr-alex"`` / account ``"state-key"``. We NEVER shell out to the
    ``security`` CLI with a secret in argv, and the key is never placed in an env var, a
    git-tracked file, or a log line.
  - Key loss = transcript loss (it fails toward privacy — accepted per D2).

Testing note: tests install an in-memory ``keyring`` backend (see ``tests/conftest.py``) so
the round-trip is deterministic and never touches — or hangs on — the real Keychain. At
runtime the real macOS Keychain backend is used.
"""

from __future__ import annotations

import base64
import secrets
import threading
from collections.abc import Callable

import keyring
from cryptography.fernet import Fernet, InvalidToken

#: Keychain service shared by every Dr. Alex secret.
SERVICE = "dr-alex"
#: Keychain account holding the state.db Fernet key.
STATE_KEY_ACCOUNT = "state-key"

_KEY_BYTES = 32  # secrets.token_bytes(32) → base64 → a valid 32-byte Fernet key

# The loaded secrets are cached per-process so the real Keychain is touched at most once
# per account per run (avoids repeated Security-framework access on the hot turn path).
_cache: dict[str, bytes] = {}
_lock = threading.Lock()


class CryptoError(RuntimeError):
    """Encryption/decryption could not be performed (e.g. wrong key, corrupt token)."""


def _generate_fernet_key() -> bytes:
    """A fresh Fernet key = base64-url(``secrets.token_bytes(32)``)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(_KEY_BYTES))


def load_or_create_secret(
    account: str,
    *,
    generator: Callable[[], bytes] = _generate_fernet_key,
) -> bytes:
    """Return the Keychain secret for ``account`` under service ``dr-alex``, minting once.

    The secret is opaque bytes; it is base64-encoded for Keychain storage and returned as the
    original bytes. Cached per-process. The generator is only invoked when no secret exists.
    """
    with _lock:
        if account in _cache:
            return _cache[account]
        existing = keyring.get_password(SERVICE, account)
        if existing:
            secret = base64.b64decode(existing)
        else:
            secret = generator()
            keyring.set_password(SERVICE, account, base64.b64encode(secret).decode("ascii"))
        _cache[account] = secret
        return secret


def reset_cache() -> None:
    """Drop the in-process secret cache (tests that swap keyring backends use this)."""
    with _lock:
        _cache.clear()


def _fernet() -> Fernet:
    return Fernet(load_or_create_secret(STATE_KEY_ACCOUNT))


def encrypt(plaintext: str | None) -> bytes | None:
    """Fernet-encrypt a free-text value. ``None`` passes through as ``None`` (SQL NULL)."""
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes | None) -> str | None:
    """Decrypt a Fernet token back to text. ``None`` → ``None``.

    Raises :class:`CryptoError` on a token this key can't open (corruption / key rotation).
    """
    if token is None:
        return None
    if isinstance(token, memoryview):
        token = bytes(token)
    try:
        return _fernet().decrypt(bytes(token)).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise CryptoError("could not decrypt a free-text column (key mismatch or corruption)") from exc


def encrypt_bytes(data: bytes) -> bytes:
    """Fernet-encrypt raw bytes (used for the G19 whole-``state.db`` backup snapshot)."""
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """Decrypt a raw-bytes Fernet token. Raises :class:`CryptoError` on a key mismatch."""
    try:
        return _fernet().decrypt(bytes(token))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise CryptoError("could not decrypt the backup snapshot (key mismatch or corruption)") from exc
