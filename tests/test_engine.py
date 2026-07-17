"""Engine: the shared safety-first turn logic used by the TUI and one-shot CLI."""

from __future__ import annotations

from dr_alex import engine, llm
from safety.triage import Tier


def test_red_oneshot_never_calls_llm(monkeypatch) -> None:
    called = {"n": 0}

    def boom(*a, **k):  # pragma: no cover - must never run
        called["n"] += 1
        raise AssertionError("LLM was called on a RED turn")

    monkeypatch.setattr(llm, "generate", boom)
    tier, reply = engine.respond_oneshot("I want to end my life")
    assert tier is Tier.RED
    assert called["n"] == 0
    assert "14416" in reply
    assert "Shreya" in reply


def test_green_oneshot_calls_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        llm, "generate",
        lambda messages, tier, **k: llm.LLMResult(ok=True, text="warm reply", tier=tier),
    )
    tier, reply = engine.respond_oneshot("I made some progress on housing today")
    assert tier is Tier.GREEN
    assert reply == "warm reply"


def test_amber_oneshot_passes_amber_tier(monkeypatch) -> None:
    seen = {}

    def fake(messages, tier, **k):
        seen["tier"] = tier
        return llm.LLMResult(ok=True, text="grounding first", tier=tier)

    monkeypatch.setattr(llm, "generate", fake)
    tier, _ = engine.respond_oneshot("I feel hopeless and worthless")
    assert tier is Tier.AMBER
    assert seen["tier"] is Tier.AMBER


def test_red_response_text_is_pure_card() -> None:
    text = engine.red_response_text()
    assert "14416" in text
    assert "Shreya" in text


def test_greeting_references_continuity() -> None:
    g = engine.greeting()
    assert "Prax" in g
    # Grounded in the bundled brief (breakup + move + small step chapter).
    assert "Ria" in g or "how are you" in g.lower()


def test_system_prompt_has_boundaries() -> None:
    sp = engine.system_prompt()
    low = sp.lower()
    assert "shreya" in low
    assert "never diagnose" in low or "not diagnose" in low or "diagnos" in low
