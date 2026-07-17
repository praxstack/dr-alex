"""Session-start memory context (Channel: READ) — assembled ONCE, held for the session.

This is Phase-3's "warm, specific greeting from real memory": at session start Dr. Alex
assembles a single fenced ``<PERSONAL_MEMORY>`` block from

  1. the continuity brief ("where we left off"),
  2. the G5 delta-banded re-orientation preamble (now-IST + last-talked band),
  3. gated ``memctl`` recall of ``sensitivity:high`` therapy memories (identity dr-alex,
     ``sensitivity_ceiling=high``), each carrying **provenance** {source, date, staleness}
     (G6), and
  4. a 30-day mood/risk-trend SEAM — a real interface with a stubbed data source until
     Phase 4's ``state.db`` lands.

**G20 (prompt-cache byte-stability):** the block is built exactly once per session and then
held immutable; per-turn additions are the user's messages, appended in the CONVERSATION
block downstream — this context is never rebuilt mid-session.

**G6 (memory honesty + trust ordering):** the block header states the trust order (real
clinicians > books > Prax's notes > prior AI selves) and the honesty rule ("you remember
what's in the archive; you forget what isn't; ask rather than pretend"). Personal memory is
``cite="forbidden"`` — it is context to be warm and specific with, not a source to quote.

**G14 (as-of semantics):** recall uses memctl's default validity filter (status=active AND
valid-as-of-now, no ``--as-of``), so superseded / invalidated facts never reach this block.
Dr. Alex adds no path that could resurrect them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from dr_alex import captoken
from dr_alex import continuity as _continuity
from dr_alex import memstore, reorient
from dr_alex.statefile import SessionState

# ---------------------------------------------------------------------------
# 30-day mood / risk trend — the Phase-4 seam (interface real, data stubbed).
# ---------------------------------------------------------------------------


@dataclass
class MoodRiskTrend:
    """A 30-day mood/risk-trend summary. Phase 4 fills this from ``state.db``.

    Kept deliberately small and numeric (a trend line, not a transcript). ``available`` is
    False for the Phase-3 stub so the context can say so honestly rather than inventing a
    trend.
    """

    available: bool = False
    window_days: int = 30
    mood_points: int = 0
    mood_latest: int | None = None
    mood_mean: float | None = None
    mood_delta: float | None = None  # end-minus-start over the window
    risk_tier_max: str | None = None  # highest tier seen in the window
    note: str | None = None

    def render(self) -> str:
        if not self.available:
            return (
                "30-day mood/risk trend: not available yet (telemetry lands Phase 4). "
                "Ask how things have been rather than citing a trend."
            )
        bits = [f"window: {self.window_days}d", f"mood points: {self.mood_points}"]
        if self.mood_latest is not None:
            bits.append(f"latest mood: {self.mood_latest}/10")
        if self.mood_mean is not None:
            bits.append(f"mean: {self.mood_mean:.1f}")
        if self.mood_delta is not None:
            arrow = "↑" if self.mood_delta > 0 else ("↓" if self.mood_delta < 0 else "→")
            bits.append(f"delta: {arrow}{abs(self.mood_delta):.1f}")
        if self.risk_tier_max:
            bits.append(f"max risk: {self.risk_tier_max}")
        line = "30-day mood/risk trend: " + ", ".join(bits) + "."
        return line + (f" {self.note}" if self.note else "")


#: The Phase-3 default trend source: honest emptiness until state.db exists.
def stub_trend(*, now: _dt.datetime) -> MoodRiskTrend:  # noqa: ARG001 - seam signature
    return MoodRiskTrend(available=False)


# ---------------------------------------------------------------------------
# G6 provenance — source / trust ordering derived from memctl metadata.
# ---------------------------------------------------------------------------

#: Trust ordering documented for the model (G6). Lower rank = more trusted.
TRUST_ORDER = (
    "real clinicians (Shreya, Dr. Joshi)",
    "the book library",
    "Prax's own notes",
    "prior AI selves (mine included)",
)

_STALE_MEMORY_DAYS = 120  # a therapy fact older than this is flagged "may be stale"


def _provenance(hit: memstore.Hit, *, now: _dt.datetime) -> tuple[str, bool]:
    """Return (source-label, is_stale) for a recalled memory (G6).

    dr-alex's own durable writes are ``type:user`` tagged therapy → "Dr. Alex's own note".
    Clinician-imported memories (Phase-3 G12 prep) would carry a clinician source tag; we
    surface whatever provenance the store metadata gives us and never overclaim.
    """
    source = "Dr. Alex's own note (prior AI self)"
    if hit.type == "reference":
        source = "reference note"
    valid = reorient.parse_iso(hit.valid_from)
    is_stale = False
    if valid is not None:
        age = (now.astimezone(_dt.timezone.utc) if now.tzinfo
               else now.replace(tzinfo=_dt.timezone.utc)) - valid
        is_stale = age.days > _STALE_MEMORY_DAYS
    return source, is_stale


# ---------------------------------------------------------------------------
# The assembled context.
# ---------------------------------------------------------------------------


@dataclass
class MemoryContext:
    preamble: str  # G5 re-orientation (now-IST + band)
    continuity_text: str | None
    personal_memory_block: str | None  # fenced <PERSONAL_MEMORY> or None when empty
    trend: MoodRiskTrend
    staleness_banner: str | None  # G8 — loud TUI banner or None
    recalled_ids: list[str] = field(default_factory=list)

    def to_system_suffix(self) -> str:
        """The immutable memory context appended to the system prompt (once, at start)."""
        parts: list[str] = ["<SESSION_START>", self.preamble, "", self.trend.render()]
        if self.personal_memory_block:
            parts += ["", self.personal_memory_block]
        parts.append("</SESSION_START>")
        return "\n".join(parts)


def _render_personal_memory_block(hits: list[memstore.Hit], *, now: _dt.datetime) -> str | None:
    if not hits:
        return None
    lines = [
        '<PERSONAL_MEMORY cite="forbidden">',
        "Real memory from Prax's therapy archive — context to be warm and SPECIFIC with, "
        "not a source to quote. You remember what's in the archive; you forget what isn't; "
        "ask rather than pretend.",
        "Trust ordering when things conflict: " + " > ".join(TRUST_ORDER) + ".",
        "",
    ]
    for i, h in enumerate(hits, 1):
        source, stale = _provenance(h, now=now)
        flag = "  [may be stale]" if stale else ""
        lines.append(
            f'[M{i}] {{source: "{source}", date: {h.valid_from}}}{flag}'
        )
        lines.append(h.snippet.strip())
        lines.append("")
    lines.append("</PERSONAL_MEMORY>")
    return "\n".join(lines)


def assemble(
    state: SessionState,
    *,
    now: _dt.datetime | None = None,
    recall_fn=memstore.recall,
    trend_fn=stub_trend,
    query: str | None = None,
    k: int = 6,
) -> MemoryContext:
    """Assemble the once-per-session memory context (G20).

    ``recall_fn`` and ``trend_fn`` are injectable seams (fake-able in tests; the default
    ``recall_fn`` shells out to gated ``memctl``). The recall query defaults to the last
    topic (a warm seed) so the highest-signal therapy facts for the live thread surface
    first; with no topic it falls back to recency/importance ranking over therapy memories.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)

    preamble = reorient.build_preamble(
        now=now, last_session_at=state.last_session_at, last_topic=state.last_topic
    )

    seed = query if query is not None else (state.last_topic or "")
    hits: list[memstore.Hit] = []
    # Session-start assembly IS the sanctioned safe path for gated recall (council D3): it
    # mints a short-lived capability token for the duration of the recall it performs here.
    try:
        with captoken.granted():
            hits = recall_fn(seed, k=k)
    except Exception:  # noqa: BLE001 - a broken store must never break session start
        hits = []

    block = _render_personal_memory_block(hits, now=now)
    trend = trend_fn(now=now)

    banner = reorient.staleness_banner(
        now=now,
        continuity_generated_at=state.continuity_generated_at,
        has_unfinalized=bool(state.unfinalized),
    )

    return MemoryContext(
        preamble=preamble,
        continuity_text=_continuity.load_continuity_text(),
        personal_memory_block=block,
        trend=trend,
        staleness_banner=banner,
        recalled_ids=[h.id for h in hits],
    )
