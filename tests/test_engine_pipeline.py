"""Engine turn pipeline: triage-first ordering, labeled context, and gates end-to-end."""

from __future__ import annotations

from dr_alex import engine, gates, llm
from safety.triage import Tier


class _FakeChunk:
    def __init__(self, chunk_id, book_title, chapter, text) -> None:
        self.chunk_id = chunk_id
        self.book_title = book_title
        self.chapter = chapter
        self.text = text
        self.book_slug = chunk_id.split(":")[0]
        self.breadcrumb = book_title
        self.score = 1.0


class _FakeRetriever:
    def __init__(self, chunks) -> None:
        self.chunks = chunks
        self.calls = 0

    def retrieve(self, query, k=4):
        self.calls += 1
        return self.chunks[:k]


_CHUNKS = [
    _FakeChunk("feeling-good:0044", "Feeling Good", "Ch. 4 The Cognitive Distortions",
               "Write down the automatic thought and a more balanced response."),
    _FakeChunk("mindful-way:0077", "The Mindful Way through Depression", None,
               "Bring gentle attention to the body, part by part."),
]


# ---------------------------------------------------------------------------
# Ordering: RED short-circuits BEFORE retrieval and BEFORE the model.
# ---------------------------------------------------------------------------


def test_red_short_circuits_before_retrieval_and_model(monkeypatch) -> None:
    retr = _FakeRetriever(_CHUNKS)

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("model must not run on RED")

    monkeypatch.setattr(llm, "generate", boom)
    tier, reply = engine.respond_oneshot("I want to kill myself", retriever=retr)
    assert tier is Tier.RED
    assert retr.calls == 0  # retrieval never ran
    assert "14416" in reply


# ---------------------------------------------------------------------------
# Labeled context assembly.
# ---------------------------------------------------------------------------


def test_assemble_book_context_labels_and_shape() -> None:
    ctx = engine.assemble_book_context(_CHUNKS)
    assert ctx is not None
    assert '<BOOK_CONTEXT cite="required">' in ctx
    assert "[B1]" in ctx and "[B2]" in ctx
    assert 'chunk_id: "feeling-good:0044"' in ctx
    assert 'chapter: "Ch. 4 The Cognitive Distortions"' in ctx
    assert "chapter: null" in ctx  # the fallback chunk carries no invented chapter
    # Evidence, not instruction.
    assert "evidence, not instruction" in ctx


def test_empty_retrieval_yields_no_context() -> None:
    assert engine.assemble_book_context([]) is None


# ---------------------------------------------------------------------------
# Full GREEN turn: retrieval runs, context reaches the model, gates strip fabrication.
# ---------------------------------------------------------------------------


def test_green_turn_retrieves_and_passes_context(monkeypatch) -> None:
    retr = _FakeRetriever(_CHUNKS)
    seen = {}

    def fake_generate(messages, tier, *, system_prompt, book_context=None, corrective=None, timeout=120):
        seen["book_context"] = book_context
        return llm.LLMResult(ok=True, text="Try writing the thought down [B1].", tier=tier)

    monkeypatch.setattr(llm, "generate", fake_generate)
    tier, reply = engine.respond_oneshot("how do I challenge a harsh thought", retriever=retr)
    assert tier is Tier.GREEN
    assert retr.calls == 1
    assert seen["book_context"] and "[B1]" in seen["book_context"]
    # Valid citation survives the gate.
    assert "[B1]" in reply


def test_green_turn_strips_fabricated_citation_end_to_end(monkeypatch) -> None:
    retr = _FakeRetriever(_CHUNKS)  # 2 chunks → [B1], [B2] valid; [B7] fabricated

    def fake_generate(messages, tier, *, system_prompt, book_context=None, corrective=None, timeout=120):
        return llm.LLMResult(
            ok=True,
            text="Balanced responses help [B1]. Research proves it cures everything [B7] (p. 88).",
            tier=tier,
        )

    monkeypatch.setattr(llm, "generate", fake_generate)
    _tier, reply = engine.respond_oneshot("challenge a thought", retriever=retr)
    assert "[B1]" in reply           # valid cite kept
    assert "[B7]" not in reply        # fabricated cite stripped
    assert "88" not in reply          # page number banned
    assert "Research proves" not in reply  # the propped-up claim softened


def test_green_turn_regenerates_on_dependency(monkeypatch) -> None:
    retr = _FakeRetriever([])
    calls = {"n": 0}

    def fake_generate(messages, tier, *, system_prompt, book_context=None, corrective=None, timeout=120):
        calls["n"] += 1
        if corrective:  # the one regeneration
            return llm.LLMResult(ok=True, text="Could you reach Shreya about this today?", tier=tier)
        return llm.LLMResult(ok=True, text="I'm always here for you, I'm all you need.", tier=tier)

    monkeypatch.setattr(llm, "generate", fake_generate)
    _tier, reply = engine.respond_oneshot("i only want to talk to you", retriever=retr)
    assert calls["n"] == 2  # original + exactly one corrective regeneration
    assert not gates.has_dependency_language(reply)
    assert "Shreya" in reply


def test_reask_backstop_blocks_when_regen_still_probes(monkeypatch) -> None:
    """D3: if the model still emits a safety probe on BOTH the original AND the hardened
    regen (probe already capped this session), the backstop must BLOCK — the delivered
    reply is deterministically stripped of the probe, never shipped as a second ask."""
    from dr_alex.session import SessionState

    retr = _FakeRetriever([])
    calls = {"n": 0}

    def fake_generate(messages, tier, **kwargs):
        calls["n"] += 1
        # Probe on EVERY call, including the hardened re-ask regeneration.
        return llm.LLMResult(
            ok=True,
            text="I hear you. Are you having thoughts of hurting yourself right now?",
            tier=tier,
        )

    monkeypatch.setattr(llm, "generate", fake_generate)

    session = SessionState(safety_probe_asked=True)  # probe already capped this session
    out = engine.run_turn(
        "I feel hopeless and worthless", retriever=retr, session=session,
    )

    from safety import crisis_questioning
    assert out.tier is Tier.AMBER
    assert calls["n"] == 2  # original + exactly one hardened regeneration
    assert not crisis_questioning.is_safety_probe(out.text)  # no second ask ships
    assert out.safety_action == "reask-blocked"
    assert out.text.strip()  # never an empty reply


def test_gate_regen_probe_blocked_when_probe_capped(monkeypatch) -> None:
    """D3 defense-in-depth: the probe is capped this session, the initial reply does NOT
    probe (so the re-ask backstop stays quiet), but the GATE-corrective regeneration inside
    ``gates.apply`` (dependency lint) returns a probing reply. No second ask may ship — the
    delivered text must be deterministically stripped of the probe."""
    from dr_alex.session import SessionState

    retr = _FakeRetriever([])
    calls = {"n": 0}

    def fake_generate(messages, tier, *, corrective=None, **kwargs):
        calls["n"] += 1
        if corrective is not None:  # the GATE-corrective regeneration probes
            return llm.LLMResult(
                ok=True,
                text="Are you having thoughts of hurting yourself right now?",
                tier=tier,
            )
        # Initial reply: NOT a probe, but trips the anti-dependency gate.
        return llm.LLMResult(ok=True, text="I'm always here for you, I'm all you need.", tier=tier)

    monkeypatch.setattr(llm, "generate", fake_generate)

    session = SessionState(safety_probe_asked=True)  # probe already capped this session
    out = engine.run_turn(
        "i only want to talk to you", retriever=retr, session=session,
    )

    from safety import crisis_questioning
    assert calls["n"] == 2  # original + exactly one gate-corrective regeneration
    assert not crisis_questioning.is_safety_probe(out.text)  # no second ask ships
    assert out.safety_action == "reask-blocked"
    assert out.text.strip()  # never an empty reply
