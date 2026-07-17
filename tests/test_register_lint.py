"""Register discipline lint (G7) — no tables, no callouts, no sign-offs in replies.

Same enforcement shape as the anti-dependency lint: detect -> one corrective
regeneration -> deterministic strip as the backstop (formatting is safe to remove).
"""

from __future__ import annotations

from dr_alex import gates

TABLE_REPLY = (
    "Here's how your words map:\n\n"
    "| What You Said | What I Hear |\n"
    "|---|---|\n"
    "| I'm behind | shame |\n\n"
    "Let's stay with the shame."
)

CALLOUT_REPLY = (
    "> [!IMPORTANT] The Keeda attacks anything that asks you to be a beginner.\n\n"
    "That's the pattern catching itself."
)

SIGNOFF_REPLY = (
    "You showed up today, and that counts.\n\n"
    "— Dr. Alex"
)

CLEAN_REPLY = "That fear makes sense. What's the smallest next thing you could try today?"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detects_table() -> None:
    assert gates.has_register_violation(TABLE_REPLY) is True


def test_detects_callout() -> None:
    assert gates.has_register_violation(CALLOUT_REPLY) is True


def test_detects_signoff() -> None:
    assert gates.has_register_violation(SIGNOFF_REPLY) is True
    assert gates.has_register_violation("nice work today.\n-- Dr Alex") is True


def test_clean_prose_is_not_flagged() -> None:
    assert gates.has_register_violation(CLEAN_REPLY) is False
    # An em-dash mid-sentence is NOT a sign-off.
    assert gates.has_register_violation("You did the hard thing — you reached out.") is False
    # A single stray pipe in prose is not a table.
    assert gates.has_register_violation("It's a coin flip | heads or tails, either way.") is False


# ---------------------------------------------------------------------------
# Deterministic strip
# ---------------------------------------------------------------------------


def test_strip_removes_table_keeps_prose() -> None:
    out = gates.strip_register(TABLE_REPLY)
    assert "|" not in out
    assert "Let's stay with the shame." in out
    assert "Here's how your words map" in out


def test_strip_removes_callout_marker_keeps_content() -> None:
    out = gates.strip_register(CALLOUT_REPLY)
    assert "[!" not in out and "> " not in out
    assert "Keeda attacks anything" in out
    assert "pattern catching itself" in out


def test_strip_removes_signoff() -> None:
    out = gates.strip_register(SIGNOFF_REPLY)
    assert "Dr. Alex" not in out
    assert "You showed up today" in out


# ---------------------------------------------------------------------------
# enforce_register: regenerate once, else strip
# ---------------------------------------------------------------------------


def test_clean_reply_passes_untouched() -> None:
    called = {"n": 0}

    def regen(_i: str) -> str:
        called["n"] += 1
        return "unused"

    out = gates.enforce_register(CLEAN_REPLY, regenerate=regen)
    assert out.action == "clean"
    assert called["n"] == 0


def test_regeneration_fixes_register() -> None:
    calls = {"n": 0}

    def regen(instr: str) -> str:
        calls["n"] += 1
        assert "table" in instr.lower() and "callout" in instr.lower()
        return "Plain prose now, no formatting at all."

    out = gates.enforce_register(TABLE_REPLY, regenerate=regen)
    assert out.action == "regenerated"
    assert calls["n"] == 1
    assert not gates.has_register_violation(out.text)


def test_persistent_violation_is_stripped_deterministically() -> None:
    calls = {"n": 0}

    def regen(_i: str) -> str:
        calls["n"] += 1
        return CALLOUT_REPLY  # model keeps the callout

    out = gates.enforce_register(CALLOUT_REPLY, regenerate=regen)
    assert out.action == "stripped"
    assert calls["n"] == 1  # only one regeneration attempt
    assert not gates.has_register_violation(out.text)
    assert "Keeda attacks anything" in out.text  # content preserved


def test_regeneration_returning_none_falls_back_to_strip() -> None:
    out = gates.enforce_register(SIGNOFF_REPLY, regenerate=lambda _i: None)
    assert out.action == "stripped"
    assert not gates.has_register_violation(out.text)


# ---------------------------------------------------------------------------
# Combined apply(): dependency -> register -> citations
# ---------------------------------------------------------------------------


class _Chunk:
    pass


def test_apply_strips_register_and_validates_citations() -> None:
    reply = (
        "Some grounding for you [B1].\n\n"
        "| What You Said | What I Hear |\n"
        "|---|---|\n"
        "| I'm behind | shame |\n"
    )
    out = gates.apply(reply, [_Chunk()], regenerate=lambda _i: None)
    assert out.register_action in ("stripped", "regenerated")
    assert not gates.has_register_violation(out.text)
    assert "[B1]" in out.text  # valid citation survives


def test_apply_clean_reply_is_untouched() -> None:
    out = gates.apply(CLEAN_REPLY, [], regenerate=lambda _i: "unused")
    assert out.dependency_action == "clean"
    assert out.register_action == "clean"
    assert out.text == CLEAN_REPLY


# ---------------------------------------------------------------------------
# G7 persona move-set (prose layer) — principles, NOT prescribed shapes.
# ---------------------------------------------------------------------------


def test_persona_documents_measured_moves_and_register() -> None:
    from dr_alex import paths

    persona = paths.read_text("persona", "dr-alex.md") or ""
    low = persona.lower()
    assert "measured moves" in low
    # the moves
    assert "one question, not three" in low
    assert "validate without rescuing" in low
    assert "silence move" in low
    assert "specific receipts" in low
    assert "refusal-as-protection" in low
    assert "same-turn shreya referral" in low
    # register discipline documented alongside the lint
    assert "no markdown tables" in low
    assert "no callout blocks" in low or "callout block" in low
    # anti-rider: principles, not formats/templates (do NOT prescribe opening shapes)
    assert "principles, not templates" in low
    assert "adopt a fixed opening shape" in low
