"""Session-start memory context: G20 once-assembly, G6 provenance, trend seam, block shape.

Recall is faked here (a real-store integration proof of G14 lives in
``test_memory_integration.py``). These assert what Dr. Alex does with what recall returns.
"""

from __future__ import annotations

import datetime as _dt

from dr_alex import memory
from dr_alex.memstore import Hit
from dr_alex.statefile import SessionState

_UTC = _dt.timezone.utc


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 9, 0, tzinfo=_UTC)


def _hit(mid: str, snippet: str, *, valid_from: str = "2026-07-10", mtype: str = "user") -> Hit:
    return Hit(id=mid, type=mtype, status="active", valid_from=valid_from, invalid_at=None,
               importance=70, sensitivity="high", score=70.0, snippet=snippet)


def test_personal_memory_block_shape_and_provenance() -> None:
    hits = [_hit("m1", "Behavioral activation lifts Prax's morning lows.")]
    ctx = memory.assemble(
        SessionState(last_topic="mornings"), now=_now(),
        recall_fn=lambda q, k=6: hits, trend_fn=memory.stub_trend,
    )
    block = ctx.personal_memory_block
    assert block is not None
    assert '<PERSONAL_MEMORY cite="forbidden">' in block
    assert "[M1]" in block
    # G6: provenance {source, date} on the entry.
    assert 'source:' in block and "2026-07-10" in block
    # G6: trust ordering documented, honesty rule present.
    assert "real clinicians" in block
    assert "forget what isn't" in block
    assert "m1" in ctx.recalled_ids


def test_stale_memory_is_flagged() -> None:
    old = _hit("m-old", "an old note", valid_from="2025-01-01")  # >120d before now
    ctx = memory.assemble(
        SessionState(), now=_now(), recall_fn=lambda q, k=6: [old],
    )
    assert "[may be stale]" in (ctx.personal_memory_block or "")


def test_empty_recall_yields_no_block_but_still_greets() -> None:
    ctx = memory.assemble(SessionState(last_topic="x"), now=_now(), recall_fn=lambda q, k=6: [])
    assert ctx.personal_memory_block is None
    # The preamble (G5) is always present.
    assert "IST" in ctx.preamble


def test_recall_seed_defaults_to_last_topic() -> None:
    seen = {}

    def fake_recall(query, k=6):
        seen["query"] = query
        return []

    memory.assemble(SessionState(last_topic="the initiation wall"), now=_now(), recall_fn=fake_recall)
    assert seen["query"] == "the initiation wall"


def test_broken_recall_never_breaks_assembly() -> None:
    def boom(query, k=6):
        raise RuntimeError("store down")

    ctx = memory.assemble(SessionState(), now=_now(), recall_fn=boom)
    assert ctx.personal_memory_block is None  # honest emptiness, no crash


def test_trend_seam_stub_is_honest() -> None:
    ctx = memory.assemble(SessionState(), now=_now(), recall_fn=lambda q, k=6: [])
    rendered = ctx.trend.render()
    assert "not available yet" in rendered
    assert "Phase 4" in rendered


def test_trend_seam_accepts_real_data() -> None:
    def trend(*, now):
        return memory.MoodRiskTrend(
            available=True, mood_points=8, mood_latest=6, mood_mean=5.2,
            mood_delta=1.5, risk_tier_max="AMBER",
        )

    ctx = memory.assemble(SessionState(), now=_now(), recall_fn=lambda q, k=6: [], trend_fn=trend)
    r = ctx.trend.render()
    assert "latest mood: 6/10" in r
    assert "↑1.5" in r
    assert "max risk: AMBER" in r


def test_system_suffix_is_stable_across_calls_G20() -> None:
    hits = [_hit("m1", "note one")]
    state = SessionState(last_topic="mornings", last_session_at="2026-07-16T09:00:00Z")
    a = memory.assemble(state, now=_now(), recall_fn=lambda q, k=6: hits).to_system_suffix()
    b = memory.assemble(state, now=_now(), recall_fn=lambda q, k=6: hits).to_system_suffix()
    # Byte-stable for the same inputs (prompt-cache friendliness).
    assert a == b
    assert "<SESSION_START>" in a and "</SESSION_START>" in a


def test_staleness_banner_surfaces_in_context() -> None:
    state = SessionState(continuity_generated_at="2026-06-01T00:00:00Z")  # >14d before now
    ctx = memory.assemble(state, now=_now(), recall_fn=lambda q, k=6: [])
    assert ctx.staleness_banner is not None
    assert "stale" in ctx.staleness_banner.lower()
