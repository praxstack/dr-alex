"""Session-end distillation, inbox digest rendering (G15 seam), continuity regeneration."""

from __future__ import annotations

import datetime as _dt
import json

from dr_alex import digest as D
from dr_alex.digest import SessionDigest, Technique

_UTC = _dt.timezone.utc


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 9, 0, tzinfo=_UTC)


_GOOD_JSON = {
    "mood_in": 3, "mood_out": 6,
    "techniques_tried": [{"name": "behavioral-activation", "efficacy": "helped"},
                         {"name": "thought-record", "efficacy": "mixed"}],
    "books_cited": ["Feeling Good"],
    "threads_open": ["the M.Tech plan avoidance"],
    "threads_closed": ["the message to Shreya"],
    "homework_assigned": ["one 30-min block tomorrow morning"],
    "key_insight": "Small, today-sized steps beat the grand plan.",
    "last_topic": "morning behavioral activation",
    "durable_learnings": ["Behavioral activation reliably lifts Prax's morning lows."],
}


def _fake_llm(payload):
    def _fn(*, turns, system_prompt, instruction, timeout):
        return payload
    return _fn


def test_distill_parses_structured_digest() -> None:
    d = D.distill(
        [("user", "rough morning"), ("assistant", "let's try a small step")],
        session_id="sess1", started_at="2026-07-18T08:00:00Z", risk_tier_max="AMBER",
        now=_now(), llm_fn=_fake_llm(json.dumps(_GOOD_JSON)),
    )
    assert d.mood_in == 3 and d.mood_out == 6
    assert [t.name for t in d.techniques] == ["behavioral-activation", "thought-record"]
    assert d.techniques[0].efficacy == "helped"
    assert d.books_cited == ["Feeling Good"]
    assert d.last_topic == "morning behavioral activation"
    assert d.durable_learnings and "morning lows" in d.durable_learnings[0]
    assert d.generation_failed is False


def test_distill_tolerates_prose_wrapped_json() -> None:
    wrapped = "Here you go:\n```json\n" + json.dumps(_GOOD_JSON) + "\n```\nDone."
    d = D.distill([], session_id="s", started_at="t", risk_tier_max="GREEN",
                  now=_now(), llm_fn=_fake_llm(wrapped))
    assert d.mood_out == 6


def test_distill_fail_loud_on_unparseable() -> None:
    d = D.distill([], session_id="s", started_at="t", risk_tier_max="GREEN",
                  now=_now(), llm_fn=_fake_llm("sorry, I can't do that"))
    assert d.generation_failed is True
    # Never fabricates durable facts from a failed distillation.
    assert d.durable_learnings == []


def test_distill_rejects_out_of_range_mood() -> None:
    d = D.distill([], session_id="s", started_at="t", risk_tier_max="GREEN", now=_now(),
                  llm_fn=_fake_llm(json.dumps({"mood_in": 42, "durable_learnings": []})))
    assert d.mood_in is None


def _digest(**over) -> SessionDigest:
    base = dict(
        session_id="sess1", started_at="2026-07-18T08:00:00Z", ended_at="2026-07-18T09:00:00Z",
        risk_tier_max="GREEN", mood_in=3, mood_out=6,
        techniques=[Technique("behavioral-activation", "helped")],
        books_cited=["Feeling Good"], threads_open=["M.Tech avoidance"],
        threads_closed=["message to Shreya"], homework_assigned=["one 30-min block"],
        key_insight="Small steps beat grand plans.",
        durable_learnings=["Behavioral activation lifts Prax's morning lows."],
    )
    base.update(over)
    return SessionDigest(**base)


def test_inbox_markdown_has_frontmatter_and_g15_namespace() -> None:
    md = D.render_inbox_markdown(_digest())
    assert "kind: session-digest" in md
    assert "agent: dr-alex" in md
    assert "risk_tier: GREEN" in md
    # G15: the gardener rollup seam is documented in the header.
    assert f"technique_namespace: {D.TECHNIQUE_NAMESPACE}" in md
    assert "behavioral-activation — helped" in md
    assert "one 30-min block" in md
    assert "durable-learning-candidates" in md


def test_inbox_markdown_red_withholds_durable_learnings() -> None:
    md = D.render_inbox_markdown(_digest(risk_tier_max="RED"))
    assert "risk_tier: RED" in md
    assert "withheld" in md
    # The specific learning text must not appear on a RED digest.
    assert "morning lows" not in md


def test_inbox_markdown_failed_digest_is_loud() -> None:
    md = D.render_inbox_markdown(_digest(generation_failed=True, durable_learnings=[]))
    assert "distillation FAILED" in md


def test_inbox_filename_shape() -> None:
    fn = D.inbox_filename("sess-ABC123", _now())
    assert fn.startswith("20260718T090000Z-dr-alex-")
    assert fn.endswith(".md")


def test_continuity_regeneration_stamps_generated_at() -> None:
    def fake(*, digest_summary, prior_brief, system_prompt, timeout):
        return "We kept it small this week — one honest block, and it landed."

    out = D.regenerate_continuity(_digest(), "prior brief", now=_now(), llm_fn=fake)
    assert "generated_at: 2026-07-18T09:00:00Z" in out
    assert "one honest block" in out


def test_continuity_falls_back_deterministically_on_llm_failure() -> None:
    def fake(*, digest_summary, prior_brief, system_prompt, timeout):
        return ""  # model unavailable

    out = D.regenerate_continuity(_digest(), None, now=_now(), llm_fn=fake)
    assert "generated_at:" in out
    # Deterministic brief carries forward the key insight / open threads.
    assert "Small steps" in out or "Still open" in out


def test_digest_jsonable_roundtrip() -> None:
    d = _digest()
    back = D.from_jsonable(D.to_jsonable(d))
    assert back.session_id == d.session_id
    assert [t.name for t in back.techniques] == [t.name for t in d.techniques]
    assert back.durable_learnings == d.durable_learnings
