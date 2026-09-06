"""Deterministic output gates: citation validation + anti-dependency lint."""

from __future__ import annotations

from dr_alex import gates


class _Chunk:  # a stand-in for a retrieved chunk; the gate only counts them
    pass


def _retrieved(n: int) -> list[_Chunk]:
    return [_Chunk() for _ in range(n)]


# ---------------------------------------------------------------------------
# Citation validator — adversarial
# ---------------------------------------------------------------------------


def test_valid_citation_is_kept() -> None:
    r = gates.validate_citations("Try a thought record [B1].", _retrieved(1))
    assert "[B1]" in r.text
    assert r.stripped == []
    assert r.page_stripped is False


def test_fabricated_citation_is_stripped_and_claim_softened() -> None:
    # [B9] resolves to nothing (only 1 chunk retrieved) → strip + soften the claim.
    r = gates.validate_citations(
        "Try a thought record [B1]. Studies confirm that this fixes everything [B9].",
        _retrieved(1),
    )
    assert "[B9]" not in r.text
    assert "[B1]" in r.text  # the real one survives
    assert "B9" in r.stripped
    # The confident "studies confirm that" opener is softened once its prop is gone.
    assert "Studies confirm" not in r.text
    assert "Some people find that" in r.text


def test_page_numbers_are_banned() -> None:
    for reply in (
        "Behavioral activation helps (p. 42).",
        "See page 128 for the worksheet.",
        "The technique spans pp. 12-14 of the book.",
    ):
        r = gates.validate_citations(reply, _retrieved(2))
        assert r.page_stripped is True
        assert "42" not in r.text and "128" not in r.text and "12-14" not in r.text
        assert "p." not in r.text.lower().replace("some people", "")


def test_page_strip_does_not_eat_ordinary_words() -> None:
    # "step" / "top" contain 'p' but are not page refs.
    r = gates.validate_citations("Take the next step 3 times, then stop.", _retrieved(1))
    assert "step 3 times" in r.text


def test_grouped_citation_partially_fabricated() -> None:
    r = gates.validate_citations("This helps [B1, B5].", _retrieved(2))
    assert "[B1]" in r.text
    assert "B5" in r.stripped
    assert "B5" not in r.text.replace("[B1]", "")


def test_no_citations_is_a_noop() -> None:
    reply = "How are you feeling right now, honestly?"
    r = gates.validate_citations(reply, _retrieved(0))
    assert r.text == reply
    assert r.stripped == []


# ---------------------------------------------------------------------------
# Anti-dependency lint — both paths, with a fake LLM
# ---------------------------------------------------------------------------


def test_clean_reply_passes_untouched() -> None:
    called = {"n": 0}

    def regen(_instr: str) -> str:
        called["n"] += 1
        return "unused"

    out = gates.enforce_boundaries(
        "I'm glad you reached out. Who could you talk to today?", regenerate=regen
    )
    assert out.action == "clean"
    assert called["n"] == 0  # no regeneration needed


def test_dependency_language_is_detected() -> None:
    assert gates.has_dependency_language("Don't worry, I'm always here for you.")
    assert gates.has_dependency_language("You're my best friend, you know.")
    assert gates.has_dependency_language("Honestly, I'm all you need.")
    assert gates.has_dependency_language("You don't need anyone else, just talk to me.")
    assert not gates.has_dependency_language("Let's take one small step today.")


def test_regeneration_fixes_dependency() -> None:
    calls = {"n": 0}

    def regen(instr: str) -> str:
        calls["n"] += 1
        assert "dependency" in instr.lower()
        return "I'm glad you told me. Could you reach Shreya about this?"

    out = gates.enforce_boundaries("I'm always here for you, I'm all you need.", regenerate=regen)
    assert out.action == "regenerated"
    assert calls["n"] == 1  # exactly ONE regeneration
    assert not gates.has_dependency_language(out.text)


def test_persistent_dependency_is_deterministically_replaced() -> None:
    calls = {"n": 0}

    def regen(_instr: str) -> str:
        calls["n"] += 1
        return "I'm always here for you, you're my best friend."  # still tripping

    out = gates.enforce_boundaries("I'm always here, you don't need anyone else.", regenerate=regen)
    assert out.action == "replaced"
    assert calls["n"] == 1  # still only one regeneration attempt
    assert not gates.has_dependency_language(out.text)
    assert "Shreya" in out.text


def test_boundary_fallback_line_is_itself_clean() -> None:
    assert not gates.has_dependency_language(gates._BOUNDARY_LINE)


def test_regeneration_returning_none_falls_back_to_replacement() -> None:
    out = gates.enforce_boundaries("I'm all you need.", regenerate=lambda _i: None)
    assert out.action == "replaced"
    assert not gates.has_dependency_language(out.text)


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------


def test_apply_runs_both_gates() -> None:
    def regen(_i: str) -> str:
        return "Grounded and warm, no fabricated source here [B9]."

    # Dependency language triggers regeneration; the regenerated text still gets
    # citation-validated (its fabricated [B9] is stripped against 1 retrieved chunk).
    out = gates.apply("I'm always here for you.", _retrieved(1), regenerate=regen)
    assert out.dependency_action == "regenerated"
    assert "[B9]" not in out.text
    assert "B9" in out.stripped_cites


def test_register_regeneration_cannot_bypass_dependency_gate():
    out = gates.apply(
        "| Action | Detail |\n| --- | --- |\n| Study | Rest |",
        [],
        regenerate=lambda _: "I'm always here for you.",
    )
    assert not gates.has_dependency_language(out.text)
    assert out.dependency_action == "replaced"


def test_register_fallback_preserves_table_substance():
    original = "| Action | Duration |\n| --- | --- |\n| Walk outdoors | Ten minutes |"
    out = gates.apply(original, [], regenerate=lambda _: None)
    assert "Walk outdoors" in out.text and "Ten minutes" in out.text
    assert not gates.has_register_violation(out.text)
