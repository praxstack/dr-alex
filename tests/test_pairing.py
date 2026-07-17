"""Device pairing gate (council D3): single-use codes, TTL, lockout, hashed tokens, revoke."""

from __future__ import annotations

import datetime as _dt

import pytest

from dr_alex import pairing


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 12, 0, 0, tzinfo=_dt.timezone.utc)


def test_pairing_code_redeems_once_and_mints_a_device_token() -> None:
    code = pairing.create_pairing_code(now=_now())
    dev = pairing.redeem_pairing_code(code, label="phone", now=_now())
    assert dev is not None and dev.token
    # The token verifies…
    assert pairing.verify_device_token(dev.token) is True
    # …and the code is single-use: a second redemption fails.
    assert pairing.redeem_pairing_code(code, now=_now()) is None


def test_pairing_code_expires_after_ttl() -> None:
    code = pairing.create_pairing_code(ttl=300, now=_now())
    later = _now() + _dt.timedelta(seconds=301)
    assert pairing.redeem_pairing_code(code, now=later) is None


def test_code_hash_is_never_stored_in_the_clear() -> None:
    code = pairing.create_pairing_code(now=_now())
    import sqlite3

    with sqlite3.connect(str(pairing.pairing_db_path())) as conn:
        rows = conn.execute("SELECT code_hmac FROM pairing_codes").fetchall()
    canon = pairing._canonical_code(code)
    # The stored value is an HMAC, not the code (or its canonical form).
    assert rows and all(canon not in r[0] and code not in r[0] for r in rows)


def test_lockout_after_five_failures() -> None:
    for _ in range(4):
        assert pairing.redeem_pairing_code("WRONGXXX", now=_now()) is None  # bad code, not yet locked
    # The 5th failure trips the lockout (raises), and subsequent attempts stay locked.
    with pytest.raises(pairing.PairingLockedOut):
        pairing.redeem_pairing_code("WRONGXXX", now=_now())
    code = pairing.create_pairing_code(now=_now())
    with pytest.raises(pairing.PairingLockedOut):
        pairing.redeem_pairing_code(code, now=_now())  # even a VALID code is refused while locked


def test_lockout_clears_after_window() -> None:
    for _ in range(4):
        pairing.redeem_pairing_code("WRONGXXX", now=_now())
    with pytest.raises(pairing.PairingLockedOut):
        pairing.redeem_pairing_code("WRONGXXX", now=_now())
    # After the lockout window a fresh valid code works again.
    after = _now() + _dt.timedelta(seconds=pairing.LOCKOUT_SECONDS + 1)
    code = pairing.create_pairing_code(now=after)
    dev = pairing.redeem_pairing_code(code, now=after)
    assert dev is not None


def test_device_list_and_revoke() -> None:
    code = pairing.create_pairing_code(now=_now())
    dev = pairing.redeem_pairing_code(code, label="iphone", now=_now())
    assert dev is not None
    devices = pairing.list_devices()
    assert any(d.id == dev.id and d.label == "iphone" and not d.revoked for d in devices)
    assert pairing.has_any_device() is True
    # Revoke → the token stops verifying.
    assert pairing.revoke_device(dev.id) is True
    assert pairing.verify_device_token(dev.token) is False
    assert pairing.has_any_device() is False


def test_bad_and_empty_tokens_are_rejected() -> None:
    assert pairing.verify_device_token(None) is False
    assert pairing.verify_device_token("") is False
    assert pairing.verify_device_token("not-a-real-token") is False
