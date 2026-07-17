"""Capability-token gate (council D3, defense-in-depth).

The two most powerful retrieval capabilities — **book_search** (per-turn book retrieval)
and **gated recall** (the ``sensitivity:high`` therapy recall) — must be reachable *only*
via the sanctioned safe path, even in-process. So the deterministic ``safety_check``
(triage) mints a short-TTL (≤60 s) HMAC capability token; the gated operations REFUSE to
run without a valid, unexpired token held for the current turn. This means a
prompt-injection or a stray code path that tries to call retrieval/recall directly can't
exfiltrate anything: without the token those operations are inert. The safe path stays the
only *useful* path.

The token is an HMAC-SHA256 over its own expiry, keyed by a 32-byte secret in the macOS
Keychain (service ``dr-alex`` / account ``captoken-key``). Verification is constant-time.
Grants are scoped with a context manager and stored in a :class:`contextvars.ContextVar`,
so a grant only covers the dynamic extent of one turn's safe path (same thread/frame).

There is NO env kill-switch: the gate is always on. Its cost is one cached Keychain read.
"""

from __future__ import annotations

import contextvars
import hmac
import logging
import secrets
import time
from contextlib import contextmanager
from hashlib import sha256

from dr_alex import crypto

_log = logging.getLogger("dr_alex.captoken")

#: Keychain account holding the HMAC signing key (under the shared ``dr-alex`` service).
CAPTOKEN_KEY_ACCOUNT = "captoken-key"

#: Council D3 hard ceiling: tokens live at most 60 seconds.
MAX_TTL_SECONDS = 60

_PREFIX = "cap"
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dr_alex_captoken", default=None
)


class CapabilityRefused(RuntimeError):
    """A gated capability was invoked without a valid capability token."""


def _signing_key() -> bytes:
    # A distinct 32-byte secret from the Fernet state key; minted once, cached.
    return crypto.load_or_create_secret(
        CAPTOKEN_KEY_ACCOUNT, generator=lambda: secrets.token_bytes(32)
    )


def _sign(expiry: int) -> str:
    msg = f"{_PREFIX}:{expiry}".encode("ascii")
    return hmac.new(_signing_key(), msg, sha256).hexdigest()


def mint(ttl: int = MAX_TTL_SECONDS, *, now: float | None = None) -> str:
    """Mint a capability token valid for ``ttl`` seconds (clamped to ≤ 60).

    Called by the sanctioned safe path (``safety_check`` / session-start assembly).
    """
    ttl = max(1, min(int(ttl), MAX_TTL_SECONDS))
    expiry = int((now if now is not None else time.time())) + ttl
    return f"{expiry}.{_sign(expiry)}"


def verify(token: str | None, *, now: float | None = None) -> bool:
    """True iff ``token`` is a well-formed, correctly-signed, unexpired capability token."""
    if not token or "." not in token:
        return False
    expiry_s, _, sig = token.partition(".")
    try:
        expiry = int(expiry_s)
    except (ValueError, TypeError):
        return False
    if not hmac.compare_digest(sig, _sign(expiry)):
        return False
    return (now if now is not None else time.time()) < expiry


@contextmanager
def granted(ttl: int = MAX_TTL_SECONDS):
    """Mint a token and hold it as the current capability for the enclosed block.

    Used by the safe path to authorize the gated retrieval/recall it then performs.
    """
    token = mint(ttl)
    reset = _current.set(token)
    try:
        yield token
    finally:
        _current.reset(reset)


def current() -> str | None:
    return _current.get()


def is_granted(*, now: float | None = None) -> bool:
    return verify(_current.get(), now=now)


def require(*, now: float | None = None) -> None:
    """Raise :class:`CapabilityRefused` unless a valid token is held for the current turn."""
    if not verify(_current.get(), now=now):
        raise CapabilityRefused("gated capability requires a valid safety-check token")
