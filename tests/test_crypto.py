"""Fernet key management + free-text encryption round-trip (council D2)."""

from __future__ import annotations

import base64

import pytest

from dr_alex import crypto


def test_roundtrip() -> None:
    token = crypto.encrypt("call Shreya about the sleep thing")
    assert isinstance(token, bytes)
    assert crypto.decrypt(token) == "call Shreya about the sleep thing"


def test_none_passthrough() -> None:
    assert crypto.encrypt(None) is None
    assert crypto.decrypt(None) is None


def test_ciphertext_is_not_plaintext() -> None:
    token = crypto.encrypt("SECRET_HOMEWORK_TITLE")
    assert b"SECRET_HOMEWORK_TITLE" not in token


def test_key_is_32_bytes_base64() -> None:
    key = crypto.load_or_create_secret(crypto.STATE_KEY_ACCOUNT)
    # A Fernet key is base64-url of exactly 32 raw bytes.
    assert len(base64.urlsafe_b64decode(key)) == 32


def test_decrypt_wrong_token_raises() -> None:
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(b"not-a-valid-fernet-token")
