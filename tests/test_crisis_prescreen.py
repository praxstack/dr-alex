"""G17 crisis prescreen: the debounce bypass reuses the deterministic RED lexicon (no drift)."""

from __future__ import annotations

import pytest

from safety import crisis_prescreen
from safety.triage import Tier, triage


@pytest.mark.parametrize("text", [
    "I want to kill myself",
    "I don't want to be here anymore",
    "mujhe marna hai",           # Hinglish explicit
    "jeena nahi chahta",         # Hinglish passive
])
def test_crisis_fragments_bypass(text: str) -> None:
    assert crisis_prescreen.is_crisis(text) is True
    bypass, reason = crisis_prescreen.should_bypass_debounce(text)
    assert bypass is True and reason == "crisis"
    # And it never diverges from the real gate.
    assert triage(text) is Tier.RED


@pytest.mark.parametrize("text", [
    "I had a rough day at work",
    "can we talk about the housing plan",
    "the movie khatam ho gayi",   # innocent Hinglish ("the movie ended")
    "",
])
def test_benign_fragments_do_not_bypass(text: str) -> None:
    assert crisis_prescreen.is_crisis(text) is False
    bypass, reason = crisis_prescreen.should_bypass_debounce(text)
    assert bypass is False and reason is None
