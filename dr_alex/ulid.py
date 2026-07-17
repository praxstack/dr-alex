"""A tiny, dependency-free ULID generator (Crockford base32, 48-bit time + 80-bit random).

ULIDs are the primary keys for state.db rows: lexicographically sortable by creation time,
collision-resistant, and — importantly for council D2 — *opaque ids*, which the plaintext
allowlist permits in the clear. We roll our own (≈20 lines) rather than add a dependency.
"""

from __future__ import annotations

import os
import time

# Crockford's base32 alphabet (no I, L, O, U).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new(*, now_ms: int | None = None) -> str:
    """A 26-character ULID. ``now_ms`` is injectable for deterministic tests."""
    ms = now_ms if now_ms is not None else int(time.time() * 1000)
    ms &= (1 << 48) - 1
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits
    return _encode(ms, 10) + _encode(rand, 16)
