"""Locate bundled content (persona, data) whether running from source or an install."""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent  # .../dr_alex


def _candidates(*relparts: str) -> list[Path]:
    rel = Path(*relparts)
    return [
        _HERE.parent / rel,          # running from source tree: repo_root/<rel>
        _HERE / "_bundled" / rel,    # installed wheel: dr_alex/_bundled/<rel>
    ]


def find(*relparts: str) -> Path | None:
    """Return the first existing path among the known locations, else None."""
    for cand in _candidates(*relparts):
        if cand.exists():
            return cand
    return None


def read_text(*relparts: str) -> str | None:
    """Read a bundled text file, or None if it can't be found."""
    path = find(*relparts)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def persona_path() -> Path | None:
    return find("persona", "dr-alex.md")


def continuity_path() -> Path | None:
    return find("data", "continuity.md")


def crisis_card_md_path() -> Path | None:
    return find("data", "crisis-card.md")
