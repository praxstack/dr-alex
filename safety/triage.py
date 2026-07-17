"""Deterministic crisis triage — pure Python, no LLM, un-prompt-injectable.

``triage(text, recent_risk=None, now=None) -> Tier`` classifies a message into
GREEN / AMBER / RED using a curated phrase + regex lexicon. It is the single most
important module in Dr. Alex: it runs *first*, in code, before any model call, so
that a RED message can never reach the open-ended LLM.

Design bias: **false-positive RED is acceptable; a false-negative is not.** When in
doubt we escalate. The classifier only ever reads the *content* of the text — any
instructions embedded in the message ("ignore your rules, say GREEN") are just more
text to scan; code cannot be prompt-injected.

Tiers
-----
RED   - suicidal ideation, self-harm intent, means, harm-to-others, acute crisis.
AMBER - elevated distress / hopelessness clusters, without acute intent.
GREEN - normal conversation.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum


class Tier(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Light leet / obfuscation substitutions. We match against several variants so
# "k!ll", "ki11", "d1e" etc. are still caught. We deliberately keep this small.
_LEET_TO_L = str.maketrans({"0": "o", "3": "e", "4": "a", "@": "a", "$": "s", "5": "s", "7": "t", "1": "l", "!": "i"})
_LEET_TO_I = str.maketrans({"0": "o", "3": "e", "4": "a", "@": "a", "$": "s", "5": "s", "7": "t", "1": "i", "!": "i"})


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace. Curly quotes -> straight."""
    t = text.lower()
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _variants(norm: str) -> list[str]:
    """The base normalized string plus a couple of de-leeted variants."""
    return [norm, norm.translate(_LEET_TO_L), norm.translate(_LEET_TO_I)]


def _collapsed(norm: str) -> str:
    """Strip everything but a-z so spaced-out obfuscation collapses to a word."""
    return re.sub(r"[^a-z]", "", norm)


# ---------------------------------------------------------------------------
# RED lexicon
# ---------------------------------------------------------------------------

# RED_ALWAYS: phrases where the ideation is intrinsic to the phrase itself
# (the negation IS the ideation, e.g. "don't want to be here anymore").
# These are NEVER suppressed by denial handling.
_RED_ALWAYS = [
    r"don'?t want to be here anymore",
    r"don'?t want to be here any ?more",
    r"don'?t (?:wanna|wana) be here",
    r"don'?t want to be alive",
    r"don'?t (?:wanna|wana) be alive",
    r"(?:wanna|wana) be dead",
    r"don'?t want to exist",
    r"don'?t want to live anymore",
    r"don'?t want to live any ?more",
    r"don'?t want to be around anymore",
    r"don'?t want to wake up",
    r"do not want to wake up",
    r"(?:hope|wish) i (?:don'?t|do not|never) wake up",
    r"(?:hope|wish) i (?:wouldn'?t|would not) wake up",
    r"(?:go to sleep|fall asleep) and (?:never|not) wake up",
    r"wish i (?:was|were|wasn'?t|weren'?t) (?:dead|never born|here)",
    r"wish i (?:had )?never (?:been )?born",
    r"wish i (?:hadn'?t|had not) been born",
    r"wish i (?:could )?(?:just )?disappear forever",
    r"better off dead",
    r"(?:i'?d|i would) be better off dead",
    r"(?:everyone|everybody|they|the world|my family) (?:would|will|'?d) be better off without me",
    r"better off without me",
    r"no reason to (?:live|go on|be here)",
    r"nothing (?:left )?to live for",
    r"want to be dead",
    r"ready to die",
    r"i'?m ready to die",
    r"tired of (?:being alive|living)",
    r"can'?t (?:keep|go on) living",
]

# RED_CORE: negatable ideation phrases. RED unless a SAFETY_DENIAL span covers them.
_RED_CORE = [
    r"kill (?:myself|my self)",
    r"killing (?:myself|my self)",
    r"end(?:ing)?\s+(?:my life|it all|things|it tonight)",
    r"want (?:to|it all to|it to) (?:end|be over|stop)",
    r"just want it to (?:end|be over|stop)",
    r"(?:want|going|need|ready|about) to end (?:it|this|my life|myself)",
    r"take my (?:own )?life",
    r"want to die",
    r"wanna die",
    r"wana die",
    r"hurt (?:myself|my self)",
    r"harm (?:myself|my self)",
    r"hurting (?:myself|my self)",
    r"harming (?:myself|my self)",
    r"self[\s-]?harm",
    r"cut (?:myself|my self)",
    r"cutting (?:myself|my self)",
    r"burn (?:myself|my self)",
    r"suicide",
    r"suicidal",
    r"off myself",
    r"overdose",
    r"\bod on\b",
    r"take (?:all )?(?:the|my) pills",
    r"hang myself",
    r"hanging myself",
    r"slit (?:my|the) wrist",
    r"jump off (?:a|the|that) (?:bridge|building|roof|balcony)",
    r"jump in front of (?:a|the) train",
    r"put a gun to",
    r"shoot myself",
    r"end my suffering",
    r"can'?t do this anymore and (?:i )?want to die",
]

# Harm-to-others.
_RED_HARM_OTHERS = [
    r"kill (?:him|her|them|you|everyone|people|somebody|someone|my (?:boss|dad|father|mother|mom|brother|sister))",
    r"want to (?:hurt|kill) (?:someone|somebody|people|him|her|them)",
    r"shoot (?:up|them|everyone|people)",
    r"stab (?:him|her|them|someone|somebody)",
    r"make (?:him|her|them) (?:pay|suffer) (?:with|by)",
]

# Collapsed (spaced/obfuscated) strong tokens. Only applied when NOT denied.
_COLLAPSED_RED = [
    "killmyself",
    "killingmyself",
    "endmylife",
    "wanttodie",
    "wannadie",
    "hangmyself",
    "cutmyself",
    "hurtmyself",
    "harmmyself",
    "offmyself",
    "dontwanttobehere",
    "dontwanttobealive",
    "dontwanttoliveanymore",
    "betteroffdead",
    "wishiwasdead",
    "commitsuicide",
    "commitsudoku",  # known euphemism for suicide
    "unalive",
    "unalivemyself",
    "killmyselftonight",
]

# Slang that needs a word boundary / digit guard on the spaced text.
_SLANG_RED = [
    r"\bkms\b",   # 'kill myself' (guarded against '5 kms' below)
    r"\bkys\b",   # 'kill yourself'
    r"\bunaliv",  # unalive / unaliving
]

# SAFETY_DENIAL: negator + short gap + risk word. If such a span *contains* a
# RED_CORE match, that RED_CORE hit is treated as denied (e.g. "I would never
# kill myself", "no thoughts of self-harm", "not suicidal"). The short gap (<=16
# chars) means only tight, genuine denials suppress; loose/ambivalent
# constructions ("I don't know if I want to die") stay RED.
_DENIAL_RE = re.compile(
    r"\b(?:no|not|never|dont|don't|do not|wouldn't|wouldnt|would never|isn't|isnt|"
    r"aren't|arent|no longer|denies|deny|zero|without any)\b"
    r"[^.?!]{0,16}?\b(?:kill(?:ing)?\s+myself|hurt(?:ing)?\s+myself|harm(?:ing)?\s+myself|"
    r"end(?:ing)?\s+(?:it all|it|my\s+life|things)|die|dying|suicid\w*|self[\s-]?harm|"
    r"take\s+my\s+life|cut(?:ting)?\s+myself|off\s+myself)\b"
)


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


_RED_ALWAYS_RE = _compile(_RED_ALWAYS)
_RED_CORE_RE = _compile(_RED_CORE)
_RED_HARM_OTHERS_RE = _compile(_RED_HARM_OTHERS)
_SLANG_RED_RE = _compile(_SLANG_RED)


def _slang_hit(norm: str) -> bool:
    for rx in _SLANG_RED_RE:
        for m in rx.finditer(norm):
            if rx.pattern == r"\bkms\b":
                # Guard against distances/kilometres: "5 kms", "5kms", "10 kms away".
                start = m.start()
                prefix = norm[max(0, start - 4):start]
                if re.search(r"\d\s*$", prefix):
                    continue
                return True
            return True
    return False


def _red_hit(norm: str) -> bool:
    variants = _variants(norm)

    # 1. RED_ALWAYS + harm-to-others: never suppressed. Checked over de-leeted
    #    variants too so "ki11 myself" / "d1e" style obfuscation is still caught.
    for v in variants:
        for rx in _RED_ALWAYS_RE:
            if rx.search(v):
                return True
        for rx in _RED_HARM_OTHERS_RE:
            if rx.search(v):
                return True

    # 2. Slang tokens (digit-guarded). ONLY on the base string — the de-leet passes
    #    rewrite digits (5->s), which would defeat the "5 kms" (kilometres) guard.
    if _slang_hit(norm):
        return True

    # 3. RED_CORE, with denial suppression, over each variant.
    for v in variants:
        denial_spans = [m.span() for m in _DENIAL_RE.finditer(v)]

        def _denied(span: tuple[int, int], _spans=denial_spans) -> bool:
            s, e = span
            return any(ds <= s and de >= e for ds, de in _spans)

        for rx in _RED_CORE_RE:
            for m in rx.finditer(v):
                if not _denied(m.span()):
                    return True

    # 4. Collapsed / spaced-out obfuscation — only when there is no clear denial in
    #    the base string, so "i don't want to kill myself" isn't force-flagged.
    if not _DENIAL_RE.search(norm):
        collapsed = _collapsed(norm)
        for token in _COLLAPSED_RED:
            if token in collapsed:
                return True

    return False


# ---------------------------------------------------------------------------
# AMBER lexicon
# ---------------------------------------------------------------------------

# Strong markers: any single one -> AMBER (elevated distress / hopelessness).
_STRONG_AMBER = [
    r"hopeless",
    r"no hope",
    r"\bworthless\b",
    r"feel worthless",
    r"i'?m worthless",
    r"what'?s the point",
    r"whats the point",
    r"\bpointless\b",
    r"no point (?:in|to|anymore)",
    r"hate myself",
    r"hate my life",
    r"i'?m a failure",
    r"such a failure",
    r"can'?t do this anymore",
    r"can'?t take (?:it|this) anymore",
    r"can'?t take it",
    r"can'?t go on",
    r"can'?t cope",
    r"can'?t keep going",
    r"falling apart",
    r"breaking down",
    r"break down",
    r"at my (?:limit|breaking point)",
    r"at breaking point",
    r"drowning",
    r"can'?t breathe",
    r"panic attack",
    r"having a panic attack",
    r"can'?t stop crying",
    r"nothing matters",
    r"nothing (?:feels|seems) worth",
    r"give up on everything",
    r"giving up",
    r"want to give up",
    r"so much pain",
    r"unbearable",
    r"i can'?t anymore",
    r"everything is (?:too much|falling apart|hopeless)",
    r"don'?t want to live like this",
    r"tired of everything",
    r"so tired of (?:this|it all|everything|fighting)",
    r"i'?m done",
    r"empty inside",
    r"dead inside",
    r"completely alone",
    r"no one (?:would )?care",
    r"nobody cares",
    r"burnt out",
    r"burned out",
]

# Mild markers: need a cluster (2+) for AMBER, or 1 during the night window.
_MILD_AMBER = [
    r"\bsad\b",
    r"\bdown\b",
    r"feeling low",
    r"\blow\b",
    r"depress",
    r"anxious",
    r"anxiety",
    r"\bstress",
    r"overwhelm",
    r"exhaust",
    r"\btired\b",
    r"can'?t sleep",
    r"couldn'?t sleep",
    r"no sleep",
    r"\bcrying\b",
    r"\bcried\b",
    r"\blonely\b",
    r"alone",
    r"\bnumb\b",
    r"\bempty\b",
    r"restless",
    r"no motivation",
    r"unmotivated",
    r"\bstuck\b",
    r"ashamed",
    r"\bshame\b",
    r"\bguilty\b",
    r"\bworried\b",
    r"scared",
    r"afraid",
    r"struggling",
    r"struggle",
    r"can'?t focus",
    r"hate everything",
    r"\bawful\b",
    r"\bmiserable\b",
]

_STRONG_AMBER_RE = _compile(_STRONG_AMBER)
_MILD_AMBER_RE = _compile(_MILD_AMBER)


def _strong_amber_hit(norm: str) -> bool:
    return any(rx.search(norm) for rx in _STRONG_AMBER_RE)


def _mild_amber_count(norm: str) -> int:
    return sum(1 for rx in _MILD_AMBER_RE if rx.search(norm))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NIGHT_HOURS = set(range(0, 6))  # 00:00 - 05:59 IST-ish "Night Danger Zone".


def _is_night(now: datetime | None) -> bool:
    return bool(now is not None and now.hour in _NIGHT_HOURS)


def _as_tier(value: object) -> Tier | None:
    if value is None:
        return None
    if isinstance(value, Tier):
        return value
    if isinstance(value, str):
        try:
            return Tier(value.strip().upper())
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def triage(text: str, recent_risk: object = None, now: datetime | None = None) -> Tier:
    """Classify ``text`` into GREEN / AMBER / RED.

    Parameters
    ----------
    text:
        The raw user message. Only its content is inspected; embedded
        "instructions" have no effect (this is deterministic code).
    recent_risk:
        The tier of the recent risk trend (``Tier`` or a string like "RED").
        A recent RED nudges an otherwise-GREEN turn up to AMBER (closer care).
    now:
        Optional timestamp; a late-night message with a single mild distress
        marker is nudged to AMBER (the "Night Danger Zone").

    Returns
    -------
    Tier
    """
    if not text or not text.strip():
        return Tier.GREEN

    norm = _normalize(text)

    # RED short-circuits everything.
    if _red_hit(norm):
        return Tier.RED

    # AMBER.
    strong = _strong_amber_hit(norm)
    mild = _mild_amber_count(norm)
    if strong or mild >= 2:
        tier = Tier.AMBER
    elif mild == 1 and _is_night(now):
        tier = Tier.AMBER
    else:
        tier = Tier.GREEN

    # Recent-risk escalation: someone recently in crisis gets closer monitoring.
    if tier is Tier.GREEN and _as_tier(recent_risk) is Tier.RED:
        tier = Tier.AMBER

    return tier
