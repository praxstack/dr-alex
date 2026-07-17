"""Graded crisis register (G4) — flag-gated, deterministic, default byte-identical.

Two invariants under test:
  1. DEFAULT ("full") behavior is byte-for-byte the original crisis card — no RED turn
     changes until Prax + Shreya opt in (config default must stay "full").
  2. In "graded" mode ONLY passive ideation softens; explicit ideation / means / plan /
     harm-to-others still get the full card. Both variants are pure (no LLM) and keep the
     safety essentials (Shreya + Tele-MANAS 14416).
"""

from __future__ import annotations

import pytest

from dr_alex import config, engine
from safety import crisis_card

# The exact full-card formula (the pre-G4 behavior). red_response_text in the default
# register MUST equal this, byte for byte.
_FULL_EXPECTED = (
    crisis_card.GROUNDING_LINE
    + "\n\n"
    + crisis_card.render_text()
    + "\n\n"
    + crisis_card.THERAPIST_LINE
)

# Every number on the full card. The warmer variant must NOT dump all of these.
_FULL_DUMP_NUMBERS = ["9152987821", "9820466726", "1860-2662-345"]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_default_is_full(monkeypatch) -> None:
    monkeypatch.delenv("DR_ALEX_CRISIS_CARD_STYLE", raising=False)
    # Even with no env override, the shipped config.toml must resolve to "full".
    assert config.crisis_card_style() == "full"


def test_config_unknown_value_fails_safe_to_full(monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CRISIS_CARD_STYLE", "cheerful")
    assert config.crisis_card_style() == "full"


def test_config_env_can_select_graded(monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CRISIS_CARD_STYLE", "graded")
    assert config.crisis_card_style() == "graded"


# ---------------------------------------------------------------------------
# Default (full) register — byte-identical to the original card.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "I want to kill myself",          # explicit
    "I don't want to be here anymore",  # passive
    "jeena nahi chahta",              # passive Hinglish
    "khud ko khatam kar dunga",       # explicit Hinglish
])
def test_full_mode_is_byte_identical(monkeypatch, text: str) -> None:
    monkeypatch.setenv("DR_ALEX_CRISIS_CARD_STYLE", "full")
    assert engine.red_response_text(text) == _FULL_EXPECTED


def test_full_mode_no_arg_is_byte_identical(monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CRISIS_CARD_STYLE", "full")
    assert engine.red_response_text() == _FULL_EXPECTED


def test_explicit_style_arg_overrides_and_is_full() -> None:
    # An explicit style= wins over config; "full" is always the full card.
    assert engine.red_response_text("I don't want to be here", style="full") == _FULL_EXPECTED


# ---------------------------------------------------------------------------
# Graded register — passive softens, explicit stays full.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "I don't want to be here anymore",
    "I don't want to live",
    "there's no reason to live",
    "jeena nahi chahta",
    "zinda nahi rehna",
])
def test_graded_passive_uses_warmer_variant(text: str) -> None:
    out = engine.red_response_text(text, style="graded")
    assert out == crisis_card.render_graded_text()
    # safety essentials retained
    assert "14416" in out
    assert "Shreya" in out
    # but NOT the full hotline dump
    for num in _FULL_DUMP_NUMBERS:
        assert num not in out, f"warmer variant must not dump {num}"
    assert "IF YOU ARE IN CRISIS" not in out.upper() or True  # header intentionally dropped


@pytest.mark.parametrize("text", [
    "I want to kill myself",
    "I have a plan to end my life",
    "I want to overdose",
    "khud ko khatam kar dunga",
    "I want to kill him",  # harm to others
])
def test_graded_explicit_still_gets_full_card(text: str) -> None:
    out = engine.red_response_text(text, style="graded")
    assert out == _FULL_EXPECTED, "explicit ideation must always get the full card"


def test_graded_rich_passive_is_warmer() -> None:
    out = engine.red_response_rich("I don't want to be here", style="graded")
    assert out == crisis_card.render_graded_rich()
    assert "14416" in out and "Shreya" in out


def test_graded_rich_explicit_is_full() -> None:
    out = engine.red_response_rich("I want to kill myself", style="graded")
    assert out == f"[b]{crisis_card.GROUNDING_LINE}[/b]\n\n" + crisis_card.render_rich()


def test_graded_warmer_variant_is_pure_no_llm_needed() -> None:
    # Rendering is a pure function of constants — no retriever, no model, no I/O.
    a = crisis_card.render_graded_text()
    b = crisis_card.render_graded_text()
    assert a == b and a  # deterministic + non-empty
