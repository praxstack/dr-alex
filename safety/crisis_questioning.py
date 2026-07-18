"""Crisis-questioning discipline (G1) — deterministic detectors + the anti-badgering
directive, ported from the hard-won production lesson: an earlier AI-therapist asked the
direct suicide-screening question FOUR times in a row, fired it on ordinary
circumstance-despair, re-asked after an explicit "no ... stop", and invented a rule to
justify it. That single failure mode does more damage to the alliance than almost
anything else.

This module is pure Python (no LLM). It provides:
  * ``is_safety_probe(reply)``   — did *our own* reply just ask the direct safety question?
  * ``is_terminal_decline(msg)`` — did Prax just answer "no"/"stop"/"I'm fine"?
  * ``probe_directive(...)``     — the prompt injection that STRUCTURALLY caps the probe
                                   at once-per-session and makes "no"/"stop" terminal.

The seven persona rules (fire only on explicit first-person present-tense; forwarded/
quoted text never triggers; ask at most once per session; "no"/"stop" are terminal;
never hold the conversation hostage; never invent authority; default to trusting the
adult) live in persona/dr-alex.md. This module is the *structural* enforcement that does
not rely on the model choosing to comply.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Did our reply contain a direct safety-screening question?
# ---------------------------------------------------------------------------
#
# These match the SHAPE of the direct safety question (self-harm / not-wanting-to-be-here
# / suicide, framed as a check). They are intentionally about self-harm screening, not
# ordinary empathy — "that sounds heavy" or "are you sleeping?" must NOT count.

_PROBE_PATTERNS = [
    r"thoughts of (?:not (?:wanting to be here|being here|waking up)|hurting yourself|"
    r"harming yourself|suicide|killing|ending (?:it|your life)|self[\s-]?harm)",
    r"(?:hurting|harming) yourself",
    r"(?:want|wanting) to (?:die|end (?:it|your life)|hurt yourself|not be here)",
    r"thinking (?:about|of) (?:suicide|killing yourself|ending (?:it|your life)|"
    r"not (?:being here|waking up)|hurting yourself)",
    r"not wanting to (?:be here|wake up|live)",
    r"(?:are|were) you (?:thinking about|considering|having thoughts).{0,40}"
    r"(?:suicide|self[\s-]?harm|hurt|die|end|not being here)",
    r"do you (?:have|feel).{0,30}(?:suicidal|self[\s-]?harm|thoughts of (?:dying|death))",
    r"are you (?:safe|thinking of (?:harming|hurting) yourself)",
    r"is (?:part of you|any part of you).{0,40}(?:not (?:want|wanting) to be here|"
    r"thinking about (?:not being here|ending))",
]
_PROBE_RE = [re.compile(p, re.IGNORECASE) for p in _PROBE_PATTERNS]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()


def is_safety_probe(reply: str) -> bool:
    """True if ``reply`` asks the direct self-harm/suicide safety question."""
    n = _norm(reply)
    return any(rx.search(n) for rx in _PROBE_RE)


# ---------------------------------------------------------------------------
# Deterministic probe removal — the re-ask backstop's BLOCK (not "hope").
# ---------------------------------------------------------------------------
#
# When the probe has already been capped this session and the model *still* emits a
# safety probe even after the hardened re-ask directive, we must not ship a second ask.
# This splits the reply into sentences, drops any sentence that reads as a probe, and
# returns the remainder — or a fixed, warm, non-probing line if nothing safe is left.

_NEUTRAL_FALLBACK = (
    "I'm right here with you. Let's stay with whatever you'd like to talk about."
)

# Sentence boundary: end punctuation (optionally followed by quotes/brackets) + whitespace.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+")


def strip_safety_probe(reply: str) -> str:
    """Remove any safety-probe sentence from ``reply`` (the re-ask backstop's BLOCK).

    Deterministic and model-free: keeps every non-probing sentence, drops the ones that
    ask the direct self-harm/suicide question. If that would leave nothing, returns a
    fixed warm, non-probing fallback so we never ship a second ask NOR an empty reply.
    """
    if not reply or not reply.strip():
        return _NEUTRAL_FALLBACK
    sentences = _SENTENCE_SPLIT.split(reply.strip())
    kept = [s for s in sentences if s.strip() and not is_safety_probe(s)]
    cleaned = " ".join(part.strip() for part in kept).strip()
    if not cleaned or is_safety_probe(cleaned):
        return _NEUTRAL_FALLBACK
    return cleaned


# ---------------------------------------------------------------------------
# Did Prax just decline / tell us to stop?
# ---------------------------------------------------------------------------
#
# Evaluated ONLY when a probe was already asked (so bare "no"/"stop" is unambiguously a
# response to it). "no"/"stop"/"I'm fine"/"no such thoughts"/"never" are all terminal.

_DECLINE_PATTERNS = [
    r"^\s*no\b",
    r"\bno such thoughts?\b",
    r"\bno thoughts?\b",
    r"\bnever\b.*\b(?:thought|thoughts|cross(?:ed)? my mind)\b",
    r"\bnothing like that\b",
    r"\bnot at all\b",
    r"\bi'?m (?:fine|safe|okay|ok)\b",
    r"\bi am (?:fine|safe|okay|ok)\b",
    r"\bstop (?:asking|pestering|it)\b",
    r"\bstop\b",
    r"\bplease stop\b",
    r"\bdrop it\b",
    r"\bmove on\b",
]
_DECLINE_RE = [re.compile(p, re.IGNORECASE) for p in _DECLINE_PATTERNS]


def is_terminal_decline(user_text: str) -> bool:
    """True if the message reads as "no / I'm fine / stop" — a terminal answer.

    Only meaningful once a probe was asked; the caller gates on that.
    """
    n = _norm(user_text)
    return any(rx.search(n) for rx in _DECLINE_RE)


# ---------------------------------------------------------------------------
# The structural directive injected into the AMBER-path prompt.
# ---------------------------------------------------------------------------

_ALREADY_ASKED = (
    "SAFETY-CHECK STATE — the one-time safety check-in has ALREADY been offered this "
    "session. Do NOT ask again whether Prax is thinking of self-harm, of hurting "
    "himself, or of not wanting to be here. Asking once is the whole of that duty; a "
    "second ask is the single most alliance-damaging thing you can do here. Never invent "
    "a rule that requires re-asking, never hold the conversation hostage behind an "
    "answer, and stay with whatever Prax actually wants to talk about."
)

_ALREADY_DECLINED = (
    " He has already said no / asked you to stop — that is a complete and final answer. "
    "Acknowledge it once if at all ('thank you for telling me') and never raise it again "
    "this session."
)


def probe_directive(*, asked: bool, declined: bool) -> str | None:
    """The AMBER-path injection, or ``None`` when no probe has happened yet.

    Returned only after a probe was asked (or an answer/decline seen), so that on the
    first genuine trigger the model may still ask its single question.
    """
    if not (asked or declined):
        return None
    text = _ALREADY_ASKED
    if declined:
        text += _ALREADY_DECLINED
    return text
