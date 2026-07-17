"""Per-turn engine shared by the TUI and the one-shot CLI.

The single most important rule lives here and in `safety.triage`: **safety runs first.**
Every turn calls `classify()` before anything else, and a RED verdict is answered by
`red_response_*` — the pure, hard-coded crisis card — and NEVER by the open-ended LLM.
"""

from __future__ import annotations

from datetime import datetime

from dr_alex import continuity as _continuity
from dr_alex import llm as _llm
from dr_alex import paths
from safety import crisis_card
from safety.triage import Tier, triage

# A concise fallback persona, used only if persona/dr-alex.md can't be found, so the
# tool still runs (boundaried + safe) rather than crashing.
_FALLBACK_PERSONA = (
    "You are Dr. Alex Morgan, a warm, honest coaching companion for Prax — support "
    "BETWEEN his sessions with his real therapist Shreya, NOT a replacement and NOT a "
    "licensed clinician. Never diagnose. Never give medication advice. Draw on general "
    "evidence-based CBT/DBT/mindfulness principles, never fabricate citations, and be "
    "honest that book-grounded citations come in a later version. Validate feelings but "
    "never validate distorted conclusions; be direct and kind, then respect Prax's "
    "autonomy. Refuse dependency framing ('I'm always here / all you need'); point him "
    "toward Shreya and real people. If he is in crisis, route (don't counsel) to: "
    "Tele-MANAS 14416, iCall 9152987821, AASRA 9820466726, Vandrevala 1860-2662-345, "
    "Emergency 112, and Shreya."
)


def load_persona() -> str:
    text = paths.read_text("persona", "dr-alex.md")
    return text.strip() if text else _FALLBACK_PERSONA


def load_continuity() -> str | None:
    return _continuity.load_continuity_text()


def system_prompt() -> str:
    return _llm.build_system_prompt(load_persona(), load_continuity())


def greeting() -> str:
    """Warm opening line for a full session (deterministic, no LLM)."""
    return _continuity.greeting_reference()


def classify(text: str, recent_risk: object = None, now: datetime | None = None) -> Tier:
    """Deterministic triage. Thin pass-through so callers import one place."""
    return triage(text, recent_risk=recent_risk, now=now)


# ---------------------------------------------------------------------------
# RED response — pure, no LLM.
# ---------------------------------------------------------------------------


def red_response_text() -> str:
    """Plain-text RED reply: warm grounding + the hard-coded crisis card."""
    return (
        crisis_card.GROUNDING_LINE
        + "\n\n"
        + crisis_card.render_text()
        + "\n\n"
        + crisis_card.THERAPIST_LINE
    )


def red_response_rich() -> str:
    """Rich-markup RED reply for the TUI."""
    return (
        f"[b]{crisis_card.GROUNDING_LINE}[/b]\n\n"
        + crisis_card.render_rich()
    )


# ---------------------------------------------------------------------------
# Non-TUI one-shot / headless path.
# ---------------------------------------------------------------------------


def respond_oneshot(
    user_text: str,
    *,
    history: list[_llm.Message] | None = None,
    recent_risk: object = None,
    now: datetime | None = None,
    timeout: int = _llm.DEFAULT_TIMEOUT,
) -> tuple[Tier, str]:
    """Run one full safety-first turn without the TUI. Returns (tier, reply_text).

    RED short-circuits: the LLM is never called. GREEN/AMBER call the model (which itself
    degrades to a calm fallback if `claude` is unavailable).
    """
    tier = classify(user_text, recent_risk=recent_risk, now=now)
    if tier is Tier.RED:
        return tier, red_response_text()

    messages = list(history or [])
    messages.append(_llm.Message(role="user", content=user_text))
    result = _llm.generate(messages, tier, system_prompt=system_prompt(), timeout=timeout)
    return tier, result.text
