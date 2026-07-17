"""Load the continuity brief and build a warm, specific-but-light greeting.

Continuity *is* the warmth: Dr. Alex should never start cold. In Phase 1 we read the
bundled snapshot of Prax's "where we left off" brief. Later phases will source this from
state.db. The greeting reference is derived deterministically from the file (no LLM), so
the opening line is safe and stable; the full brief is also passed to the model as context
so its first real reply can be specific.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dr_alex import paths

_FALLBACK_REFERENCE = (
    "It's good to see you. How are you right now, Prax — honestly, this moment?"
)

# A curated line grounded in the brief. Used only when the brief is present and still
# describes the same chapter (breakup + move + the one-small-step thread), so we never
# assert stale specifics. If the brief changes materially, we fall back to the gentle
# generic opener above.
_GROUNDED_REFERENCE = (
    "Last time we were sitting with a lot at once — the move out of Ria's place, the "
    "grief, and the pull toward a big plan when the real ask was small: one honest "
    "30-minute block and looking at one room. No pressure to pick that up now. "
    "How are you today, Prax?"
)


def load_continuity_text() -> str | None:
    """Full continuity brief text, or None if unavailable."""
    return paths.read_text("data", "continuity.md")


def continuity_write_path() -> Path:
    """Where a regenerated brief is written (the source-tree ``data/continuity.md``)."""
    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / "continuity.md"


def save_continuity_text(text: str) -> Path:
    """Write the continuity brief 0600 under a 0700 ``data/`` dir (clinical, gitignored)."""
    p = continuity_write_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    p.write_text(text, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def greeting_reference(text: str | None = None) -> str:
    """A short, warm opener that lightly references where we left off.

    Deterministic: derived from the brief's content markers, never model-generated.
    """
    if text is None:
        text = load_continuity_text()
    if not text:
        return _FALLBACK_REFERENCE

    low = text.lower()
    # Only use the specific grounded line if the brief still matches that chapter.
    markers = ("ria", "30-min", "shahjahanpur")
    if all(m in low for m in markers):
        return _GROUNDED_REFERENCE

    # Otherwise, try to pull the "Where we left off" sentence and gentle it down.
    m = re.search(r"where we left off:\*?\s*(.+?)(?:\n\n|\Z)", text, re.IGNORECASE | re.DOTALL)
    if m:
        snippet = re.sub(r"\s+", " ", m.group(1)).strip()
        # Keep only the first sentence, cap length.
        first = re.split(r"(?<=[.?!]) ", snippet)[0]
        if len(first) > 240:
            first = first[:237].rstrip() + "..."
        return f"Last time: {first} How are you today, Prax?"

    return _FALLBACK_REFERENCE
