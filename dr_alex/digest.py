"""Session-end distillation → structured digest → inbox markdown + continuity brief.

At session end ONE distillation call (routed through the single model entrypoint, and
fully fake-able in tests) turns the conversation into a structured :class:`SessionDigest`:
``mood_in/out``, ``risk_tier_max``, ``techniques_tried`` + efficacy, ``books_cited``,
``threads_open/closed``, ``homework_assigned``, ``key_insight``, and a small set of durable
learning candidates. That digest drives the three-channel fan-out (see :mod:`dr_alex.fanout`):

  - Channel C — the full digest is rendered to markdown for ``~/agent-memory/inbox/`` where
    the EXISTING nightly gardener consolidates it. The frontmatter carries a **G15**
    ``technique_namespace`` convention so the gardener can later roll up per-technique
    efficacy facts (we document the seam; we do not build gardener config here).
  - the continuity brief is regenerated from the digest + the prior brief (also a fake-able
    model call), stamped with ``generated_at`` for the **G8** staleness contract.

Fail-loud: if distillation can't be parsed, we emit a placeholder digest flagged
``generation_failed`` with **zero** durable-learning candidates (never fabricate clinical
facts), and the fan-out writes an inbox digest that points a human at the situation.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field

#: G15 — the namespace the gardener will use to roll up per-technique efficacy facts.
TECHNIQUE_NAMESPACE = "dr-alex/technique"

_DISTILL_SYSTEM = (
    "You are the session-end distiller for Dr. Alex Morgan, a therapy-support companion for "
    "Prax. You summarize ONE finished conversation into a compact structured record for a "
    "private clinical memory store. Be faithful and conservative: never invent a technique, "
    "a mood number, a book, or a homework item that isn't supported by the conversation. "
    "Durable learnings must be genuinely durable, generalizable facts about what helps Prax "
    "(not play-by-play). Output STRICT JSON only, no prose around it."
)

_DISTILL_INSTRUCTION = (
    "Distill the conversation above into a single JSON object with EXACTLY these keys:\n"
    '  "mood_in": integer 1-10 or null,\n'
    '  "mood_out": integer 1-10 or null,\n'
    '  "techniques_tried": array of {"name": string, "efficacy": one of '
    '["helped","mixed","did-not-help","unknown"]},\n'
    '  "books_cited": array of strings (book titles referenced),\n'
    '  "threads_open": array of short strings (unresolved threads),\n'
    '  "threads_closed": array of short strings (threads that resolved),\n'
    '  "homework_assigned": array of short strings,\n'
    '  "key_insight": short string or null,\n'
    '  "last_topic": short string naming the main thread (for next-session re-orientation),\n'
    '  "durable_learnings": array of short strings — generalizable facts about what helps '
    "Prax; [] if none are clearly durable.\n"
    "Return ONLY the JSON object."
)


# ---------------------------------------------------------------------------
# The structured digest.
# ---------------------------------------------------------------------------


@dataclass
class Technique:
    name: str
    efficacy: str = "unknown"  # helped | mixed | did-not-help | unknown


@dataclass
class SessionDigest:
    session_id: str
    started_at: str
    ended_at: str
    risk_tier_max: str  # GREEN | AMBER | RED (from the live session, not the model)
    mood_in: int | None = None
    mood_out: int | None = None
    techniques: list[Technique] = field(default_factory=list)
    books_cited: list[str] = field(default_factory=list)
    threads_open: list[str] = field(default_factory=list)
    threads_closed: list[str] = field(default_factory=list)
    homework_assigned: list[str] = field(default_factory=list)
    key_insight: str | None = None
    last_topic: str | None = None
    durable_learnings: list[str] = field(default_factory=list)
    generation_failed: bool = False


def to_jsonable(digest: SessionDigest) -> dict:
    """Serialize a digest for the crash-safety marker (JSON round-trippable)."""
    return {
        "session_id": digest.session_id,
        "started_at": digest.started_at,
        "ended_at": digest.ended_at,
        "risk_tier_max": digest.risk_tier_max,
        "mood_in": digest.mood_in,
        "mood_out": digest.mood_out,
        "techniques": [{"name": t.name, "efficacy": t.efficacy} for t in digest.techniques],
        "books_cited": list(digest.books_cited),
        "threads_open": list(digest.threads_open),
        "threads_closed": list(digest.threads_closed),
        "homework_assigned": list(digest.homework_assigned),
        "key_insight": digest.key_insight,
        "last_topic": digest.last_topic,
        "durable_learnings": list(digest.durable_learnings),
        "generation_failed": digest.generation_failed,
    }


def from_jsonable(d: dict) -> SessionDigest:
    """Reconstruct a digest from the crash-safety marker."""
    return SessionDigest(
        session_id=str(d.get("session_id", "")),
        started_at=str(d.get("started_at", "")),
        ended_at=str(d.get("ended_at", "")),
        risk_tier_max=str(d.get("risk_tier_max", "GREEN")),
        mood_in=d.get("mood_in"),
        mood_out=d.get("mood_out"),
        techniques=[Technique(name=t.get("name", ""), efficacy=t.get("efficacy", "unknown"))
                    for t in d.get("techniques", []) if isinstance(t, dict) and t.get("name")],
        books_cited=list(d.get("books_cited", [])),
        threads_open=list(d.get("threads_open", [])),
        threads_closed=list(d.get("threads_closed", [])),
        homework_assigned=list(d.get("homework_assigned", [])),
        key_insight=d.get("key_insight"),
        last_topic=d.get("last_topic"),
        durable_learnings=list(d.get("durable_learnings", [])),
        generation_failed=bool(d.get("generation_failed", False)),
    )


# ---------------------------------------------------------------------------
# Parsing helpers (robust to models that wrap JSON in prose / fences).
# ---------------------------------------------------------------------------

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    m = _JSON_OBJ.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _as_mood(value: object) -> int | None:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
    return n if 1 <= n <= 10 else None


def _str_list(value: object, *, cap: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= cap:
            break
    return out


def _techniques(value: object) -> list[Technique]:
    if not isinstance(value, list):
        return []
    valid_eff = {"helped", "mixed", "did-not-help", "unknown"}
    out: list[Technique] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            eff = item.get("efficacy")
            out.append(Technique(
                name=item["name"].strip(),
                efficacy=eff if eff in valid_eff else "unknown",
            ))
        elif isinstance(item, str) and item.strip():
            out.append(Technique(name=item.strip()))
        if len(out) >= 12:
            break
    return out


# ---------------------------------------------------------------------------
# Distillation — the single model call (fake-able seam).
# ---------------------------------------------------------------------------


def _default_llm(*, turns: list[tuple[str, str]], system_prompt: str, instruction: str,
                 timeout: int) -> str:
    """Route the distillation through the ONE model entrypoint (Directive 1).

    Imported lazily so tests can fake distillation without importing the model stack.
    """
    from dr_alex import llm
    from safety.triage import Tier, TriageResult

    messages = [
        llm.Message(role=("user" if role == "user" else "assistant"), content=text)
        for role, text in turns
    ]
    result = llm.complete(
        TriageResult(tier=Tier.GREEN),
        messages,
        system_prompt=system_prompt,
        instruction=instruction,
        timeout=timeout,
    )
    return result.text if result.ok else ""


def distill(
    turns: list[tuple[str, str]],
    *,
    session_id: str,
    started_at: str,
    risk_tier_max: str,
    now: _dt.datetime,
    llm_fn=_default_llm,
    timeout: int = 90,
) -> SessionDigest:
    """Produce the structured digest from the conversation (one model call, fake-able).

    On any parse failure returns a placeholder digest flagged ``generation_failed`` with no
    durable learnings — we never invent clinical facts from an unparseable distillation.
    """
    ended_at = _iso(now)
    raw = ""
    try:
        raw = llm_fn(
            turns=turns, system_prompt=_DISTILL_SYSTEM,
            instruction=_DISTILL_INSTRUCTION, timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - a distiller crash must not crash session end
        raw = ""

    data = _extract_json(raw)
    if data is None:
        return SessionDigest(
            session_id=session_id, started_at=started_at, ended_at=ended_at,
            risk_tier_max=risk_tier_max, generation_failed=True,
        )

    last_topic = data.get("last_topic")
    return SessionDigest(
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        risk_tier_max=risk_tier_max,
        mood_in=_as_mood(data.get("mood_in")),
        mood_out=_as_mood(data.get("mood_out")),
        techniques=_techniques(data.get("techniques_tried")),
        books_cited=_str_list(data.get("books_cited")),
        threads_open=_str_list(data.get("threads_open")),
        threads_closed=_str_list(data.get("threads_closed")),
        homework_assigned=_str_list(data.get("homework_assigned")),
        key_insight=(data.get("key_insight") or None) if isinstance(data.get("key_insight"), str)
        else None,
        last_topic=last_topic.strip() if isinstance(last_topic, str) and last_topic.strip()
        else None,
        durable_learnings=_str_list(data.get("durable_learnings")),
    )


# ---------------------------------------------------------------------------
# Channel C — the inbox digest markdown.
# ---------------------------------------------------------------------------


def _iso(now: _dt.datetime) -> str:
    dt = now.astimezone(_dt.timezone.utc) if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def inbox_filename(session_id: str, now: _dt.datetime) -> str:
    dt = now.astimezone(_dt.timezone.utc) if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)
    ts = dt.strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-zA-Z0-9]", "", session_id).lower()[:8] or "session0"
    return f"{ts}-dr-alex-{slug}.md"


def render_inbox_markdown(digest: SessionDigest) -> str:
    """The full digest document dropped into ``inbox/`` for the gardener (pre-scrub).

    Frontmatter carries the G15 ``technique_namespace`` rollup convention. RED sessions are
    marked ``risk_tier: RED`` so the gardener/human treats durable writes conservatively.
    """
    fm = [
        "---",
        "kind: session-digest",
        "agent: dr-alex",
        f"session_id: {digest.session_id}",
        f"ts: {digest.ended_at}",
        "source: dr-alex-session-end",
        f"risk_tier: {digest.risk_tier_max}",
        # G15: gardener seam — per-technique efficacy rolls up under this namespace.
        f"technique_namespace: {TECHNIQUE_NAMESPACE}",
        "---",
    ]

    body: list[str] = []
    if digest.generation_failed:
        body += [
            "## distillation FAILED (fail-loud placeholder)",
            "",
            "The session-end distillation could not be parsed into a structured digest. "
            "No durable learnings were written. A human should review this session; the "
            "conversation itself was not persisted here (transcripts stay in-session until "
            "Phase 4).",
            "",
        ]

    body += ["## session", ""]
    body.append(f"- window: {digest.started_at} → {digest.ended_at}")
    body.append(f"- risk (max this session): {digest.risk_tier_max}")
    mood = []
    if digest.mood_in is not None:
        mood.append(f"in {digest.mood_in}/10")
    if digest.mood_out is not None:
        mood.append(f"out {digest.mood_out}/10")
    body.append("- mood: " + (" → ".join(mood) if mood else "not recorded"))
    body.append("")

    body += ["## techniques tried (+ efficacy)", ""]
    if digest.techniques:
        body += [f"- {t.name} — {t.efficacy}" for t in digest.techniques]
    else:
        body.append("- (none this session)")
    body.append("")

    body += ["## books cited", ""]
    body += ([f"- {b}" for b in digest.books_cited] if digest.books_cited else ["- (none)"])
    body.append("")

    body += ["## threads", ""]
    body.append("- open: " + ("; ".join(digest.threads_open) if digest.threads_open else "(none)"))
    body.append("- closed: " + ("; ".join(digest.threads_closed) if digest.threads_closed else "(none)"))
    body.append("")

    body += ["## homework assigned", ""]
    body += ([f"- {h}" for h in digest.homework_assigned] if digest.homework_assigned else ["- (none)"])
    body.append("")

    body += ["## key insight", "", (digest.key_insight or "(none recorded)"), ""]

    body += ["## durable-learning-candidates", ""]
    if digest.risk_tier_max == "RED":
        body.append("- (withheld — RED session; durable writes are conservative)")
    elif digest.durable_learnings:
        body += [f"- {d}" for d in digest.durable_learnings]
    else:
        body.append("- (none)")
    body.append("")

    return "\n".join(fm) + "\n\n" + "\n".join(body) + "\n"


# ---------------------------------------------------------------------------
# Continuity brief regeneration (fake-able model call, G8 generated_at stamp).
# ---------------------------------------------------------------------------

_CONTINUITY_SYSTEM = (
    "You write Dr. Alex Morgan's private continuity brief for Prax — a short, warm "
    "'where we left off' note (a few sentences, plain prose, no headings, no lists) that "
    "lets the next session start specific and human. Faithful to the digest; never invent."
)


def _default_continuity_llm(*, digest_summary: str, prior_brief: str, system_prompt: str,
                            timeout: int) -> str:
    from dr_alex import llm
    from safety.triage import Tier, TriageResult

    prompt_body = (
        "PRIOR BRIEF:\n" + (prior_brief or "(none)") + "\n\nTHIS SESSION (digest):\n" + digest_summary
    )
    messages = [llm.Message(role="user", content=prompt_body)]
    result = llm.complete(
        TriageResult(tier=Tier.GREEN),
        messages,
        system_prompt=system_prompt,
        instruction=(
            "Write the updated continuity brief (3-6 warm plain-prose sentences). Carry "
            "forward still-open threads; fold in what shifted this session. No headings, no "
            "lists, no sign-off."
        ),
        timeout=timeout,
    )
    return result.text if result.ok else ""


def _digest_summary_text(digest: SessionDigest) -> str:
    parts = [f"risk_max={digest.risk_tier_max}"]
    if digest.mood_in is not None or digest.mood_out is not None:
        parts.append(f"mood {digest.mood_in}→{digest.mood_out}")
    if digest.techniques:
        parts.append("techniques: " + ", ".join(f"{t.name}({t.efficacy})" for t in digest.techniques))
    if digest.threads_open:
        parts.append("open: " + "; ".join(digest.threads_open))
    if digest.threads_closed:
        parts.append("closed: " + "; ".join(digest.threads_closed))
    if digest.homework_assigned:
        parts.append("homework: " + "; ".join(digest.homework_assigned))
    if digest.key_insight:
        parts.append("insight: " + digest.key_insight)
    return "\n".join(parts)


def _deterministic_brief(digest: SessionDigest) -> str:
    """A safe, model-free continuity brief when regeneration is unavailable."""
    bits: list[str] = []
    if digest.key_insight:
        bits.append(digest.key_insight.strip().rstrip("."))
    if digest.threads_open:
        bits.append("Still open: " + "; ".join(digest.threads_open))
    if digest.homework_assigned:
        bits.append("Homework: " + "; ".join(digest.homework_assigned))
    if digest.mood_out is not None:
        bits.append(f"Mood ended around {digest.mood_out}/10")
    body = ". ".join(bits) if bits else "We touched base; nothing durable to carry forward yet."
    return "**Where we left off:** " + body + "."


def regenerate_continuity(
    digest: SessionDigest,
    prior_brief: str | None,
    *,
    now: _dt.datetime,
    llm_fn=_default_continuity_llm,
    timeout: int = 60,
) -> str:
    """Regenerate the continuity brief markdown (G8 ``generated_at`` header stamped).

    Uses the model when available; falls back to a deterministic brief so a model outage
    never leaves the next session without continuity (it just gets a plainer one).
    """
    generated = ""
    try:
        generated = llm_fn(
            digest_summary=_digest_summary_text(digest),
            prior_brief=prior_brief or "",
            system_prompt=_CONTINUITY_SYSTEM,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        generated = ""
    brief = generated.strip() if generated and generated.strip() else _deterministic_brief(digest)
    header = f"<!-- generated_at: {_iso(now)} · source: dr-alex-session-end -->"
    return header + "\n\n" + brief + "\n"
