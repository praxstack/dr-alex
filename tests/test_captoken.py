"""Capability-token gate (council D3): mint/verify/expiry + refusal semantics."""

from __future__ import annotations

import time

import pytest

from dr_alex import captoken


def test_mint_then_verify() -> None:
    tok = captoken.mint(30)
    assert captoken.verify(tok)


def test_ttl_is_clamped_to_60s() -> None:
    now = 1_000_000.0
    tok = captoken.mint(9999, now=now)
    # Valid at +59s, invalid at +61s (proves the ≤60s clamp).
    assert captoken.verify(tok, now=now + 59)
    assert not captoken.verify(tok, now=now + 61)


def test_expired_token_is_refused() -> None:
    now = 500.0
    tok = captoken.mint(10, now=now)
    assert captoken.verify(tok, now=now + 5)
    assert not captoken.verify(tok, now=now + 11)


def test_tampered_token_is_refused() -> None:
    tok = captoken.mint(30)
    expiry, _, sig = tok.partition(".")
    forged = f"{int(expiry) + 3600}.{sig}"  # push expiry out, keep the old signature
    assert not captoken.verify(forged)
    assert not captoken.verify("garbage")
    assert not captoken.verify("")


def test_require_without_grant_raises() -> None:
    with pytest.raises(captoken.CapabilityRefused):
        captoken.require()


def test_require_inside_grant_passes() -> None:
    assert not captoken.is_granted()
    with captoken.granted():
        assert captoken.is_granted()
        captoken.require()  # does not raise
    # Grant is scoped: it is gone once the block exits.
    assert not captoken.is_granted()


def test_grant_is_short_lived() -> None:
    with captoken.granted(1):
        assert captoken.is_granted()
        time.sleep(1.2)
        assert not captoken.is_granted(now=time.time())
