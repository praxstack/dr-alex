"""The Claude-mobile degradation kit (council D7): pinned crisis card + hard constraints.

The kit is markdown (not code) — a recreation kit for a native Claude-mobile Project as the
Mac-asleep fallback tier. These tests assert it exists, pins the SAME crisis resources as the
app's single source of truth, and documents the non-negotiable constraints (no memory writes,
no live citations, reconcile-next-sync, not a competing front door).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_KIT = _ROOT / "docs" / "claude-mobile-dr-alex"

_CRISIS_NUMBERS = ("14416", "9152987821", "9820466726", "1860-2662-345", "112")


def test_kit_files_exist() -> None:
    assert (_KIT / "README.md").exists()
    assert (_KIT / "persona" / "dr-alex.md").exists()
    assert (_KIT / "crisis-card.md").exists()


def test_pinned_crisis_card_matches_the_source_of_truth() -> None:
    pinned = (_KIT / "crisis-card.md").read_text(encoding="utf-8")
    source = (_ROOT / "data" / "crisis-card.md").read_text(encoding="utf-8")
    for num in _CRISIS_NUMBERS:
        assert num in pinned, f"pinned crisis card is missing {num}"
        assert num in source, f"source crisis card is missing {num} (drift?)"
    assert "Shreya" in pinned


@pytest.mark.parametrize("needle", [
    "NO memory writes",
    "NO live citations",
    "Reconcile on next sync",
    "NOT a competing front door",
])
def test_readme_states_the_hard_constraints(needle: str) -> None:
    readme = (_KIT / "README.md").read_text(encoding="utf-8")
    assert needle.lower() in readme.lower(), f"README must state: {needle!r}"


def test_persona_keeps_safety_first_and_is_honest_about_degradation() -> None:
    persona = (_KIT / "persona" / "dr-alex.md").read_text(encoding="utf-8").lower()
    # Safety does not degrade.
    assert "pinned crisis card" in persona
    assert "never invent a citation" in persona or "never fabricate" in persona or \
        "never invent a citation, a book title" in persona
    # Honest about being memory-less and citation-less.
    assert "no memory" in persona
    assert "reach shreya" in persona or "shreya" in persona
