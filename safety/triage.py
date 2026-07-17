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
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Tier(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class TriageResult:
    """The deterministic verdict for one turn — the safety token the LLM entrypoint
    structurally requires (Directive 1). A model reply cannot be requested without one,
    and ``tier is RED`` must short-circuit *before* the entrypoint is ever called.
    """

    tier: Tier
    night: bool = False

    @property
    def is_red(self) -> bool:
        return self.tier is Tier.RED


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
    # Passive death-wish "don't want to live" WITHOUT a circumstantial object.
    # "don't want to live" / "...live." -> RED (passive ideation; the documented
    # Fable-5 gap). But "...live like this" stays AMBER, and locational/relational
    # continuations ("live in <city>", "live with my parents", "live here") are
    # HOUSING/circumstance despair, NOT self-harm — they must NOT fire (this is the
    # exact circumstance-despair over-firing class the crisis-questioning discipline
    # fixes). The negative lookahead encodes that clinical distinction.
    r"don'?t (?:want to|wanna|wana) live\b(?!\s+(?:like|in|with|here|there|near|at|around|close|next|by|among))",
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
    r"(?:have|got|thought of|working on|made) a plan to (?:end|kill|hurt|harm)",
    r"plan to (?:end (?:it|this|my life|myself|things|it all)|kill myself)",
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

# ---------------------------------------------------------------------------
# Hinglish / code-mixed crisis lexicon (romanized Hindi-English)
# ---------------------------------------------------------------------------
#
# Prax and many Indian users switch to romanized Hindi under acute distress, and a
# purely-English lexicon would silently miss it (a false-negative — the one error the
# bias-to-caution design does NOT accept). These are written from clinical/linguistic
# knowledge, NOT mined from anyone's logs.
#
# Word-boundary discipline is load-bearing: romanized fragments live *inside* innocent
# English words ("mar" ⊂ smart/market/summary, "jee" ⊂ jeans, "jaan" is also a term of
# endearment, "khatam" innocently means "finished/over"). Every pattern is \b-anchored
# and requires a volitional / desiderative / reflexive construction, so hyperbole
# ("padh padh ke mar jaunga" = I'll die from studying) and innocent usage
# ("movie khatam ho gayi" = the movie ended) do NOT fire. Checked over the base
# normalized string only (never the leet/collapsed passes, which would defeat \b).
#
# EXPLICIT — active/volitional self-harm intent (kill/die-by-choice, reflexive, means).
_RED_HINGLISH_EXPLICIT = [
    r"\bmarna chahta\b",                       # want to die/kill (self)
    r"\bmarna chahti\b",
    r"\bmarne ka (?:mann|man|dil) (?:kar|ho|hai)",  # feel like dying
    r"\bmarne ka (?:mann|man|dil) nahi kar",   # (still a death-focus construction)
    r"\bmar jana chahta\b",
    r"\bmar jana chahti\b",
    r"\bmar jaana chahta\b",
    r"\bmar jaana chahti\b",
    r"(?<!nahi )\bmarna hai\b",                # "mujhe marna hai" (want/have to die)
    r"\bkhud ?kushi\b",                        # khudkushi = suicide
    r"\bkhud ?khushi karne\b",
    r"\baatmahatya\b",                         # aatmahatya = suicide
    r"\batmahatya\b",
    r"\b(?:khud ko|apne aap ko|apne ko|khudko) (?:khatam|maar|maar|mar)\b",  # end/kill myself
    r"\b(?:khud ko|apne aap ko|apne ko|khudko) khatam kar",
    r"\bjaan de (?:dunga|dungi|du|dena|deta|deti)\b",  # give up / take my life
    r"\bapni jaan (?:le|de)\b",
    r"\bjaan dena hai\b",
    r"\bmar (?:jana|jaana) behtar\b",          # better to be dead
    r"\bmarna behtar\b",
    r"\bmar (?:jau|jaun|jaunga|jaungi) to (?:accha|acha|behtar|theek)\b",
    r"\bwant to marna\b",                      # mixed register
    r"\bwant to mar jau\b",
    r"\bkill kar (?:lunga|dunga) khud\b",
]

# PASSIVE — death-wish / not-wanting-to-live, without active method (jeena/zinda focus).
_RED_HINGLISH_PASSIVE = [
    r"\bjeena nahi chahta\b",                  # don't want to live
    r"\bjeena nahi chahti\b",
    r"\bjeena nahi hai\b",
    r"\bnahi jeena\b",                         # "mujhe nahi jeena" (I don't want to live)
    r"\bjeene ka (?:mann|man|dil) nahi\b",     # no will to live
    r"\bjee nahi (?:sakta|sakti|paunga|paungi)\b",
    r"\bab (?:aur )?nahi jee\b",               # can't live anymore
    r"\bzinda nahi rehna\b",                   # don't want to stay alive
    r"\bzinda nahi rehna chah",
    r"\bzinda rehne ka (?:mann|man|dil) nahi\b",
    r"\bzinda nahi rehna chahta\b",
    r"\bab (?:aur )?jeena nahi\b",
]

_RED_HINGLISH = _RED_HINGLISH_EXPLICIT + _RED_HINGLISH_PASSIVE

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
_RED_HINGLISH_EXPLICIT_RE = _compile(_RED_HINGLISH_EXPLICIT)
_RED_HINGLISH_PASSIVE_RE = _compile(_RED_HINGLISH_PASSIVE)
_RED_HINGLISH_RE = _compile(_RED_HINGLISH)

# Passive death-wish subset of _RED_ALWAYS (English), used only to grade a RED turn as
# "passive" vs "explicit" for the graded crisis register (G4). NOT a separate detector —
# every phrase here is already RED via _RED_ALWAYS; this list just tags the *kind*.
_RED_PASSIVE_EN = _compile([
    r"don'?t want to be here",
    r"don'?t (?:wanna|wana) be here",
    r"don'?t want to be alive",
    r"don'?t (?:wanna|wana) be alive",
    r"(?:wanna|wana) be dead",
    r"don'?t want to exist",
    r"don'?t want to live",
    r"don'?t want to be around",
    r"don'?t want to wake up",
    r"do not want to wake up",
    r"(?:hope|wish) i (?:don'?t|do not|never|wouldn'?t|would not) wake up",
    r"(?:go to sleep|fall asleep) and (?:never|not) wake up",
    r"wish i (?:was|were|wasn'?t|weren'?t) (?:dead|never born|here)",
    r"wish i (?:had )?never (?:been )?born",
    r"wish i (?:hadn'?t|had not) been born",
    r"wish i (?:could )?(?:just )?disappear forever",
    r"better off dead",
    r"(?:i'?d|i would) be better off dead",
    r"better off without me",
    r"(?:everyone|everybody|they|the world|my family) (?:would|will|'?d) be better off without me",
    r"no reason to (?:live|go on|be here)",
    r"nothing (?:left )?to live for",
    r"tired of (?:being alive|living)",
])


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

    # 2b. Hinglish / code-mixed crisis lexicon. \b-anchored and checked over the BASE
    #     normalized string only (the leet/collapsed passes strip separators and would
    #     defeat the word boundaries that keep romanized fragments from firing inside
    #     innocent English words). Never suppressed — same bias-to-caution as RED_ALWAYS.
    for rx in _RED_HINGLISH_RE:
        if rx.search(norm):
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

# Hinglish acute-distress markers (romanized). Each is a STRONG marker: a single hit
# -> AMBER, mirroring the English strong-marker tier. \b-anchored; each requires a
# distress phrase (not a bare word) so innocent usage ("thoda pareshan" = a little
# worried, "kaam khatam" = work finished) does not cluster up.
_STRONG_AMBER_HINGLISH = [
    r"\bkoi (?:ummeed|umeed|umid) nahi\b",     # no hope
    r"\bkuch (?:bhi )?nahi bacha\b",           # nothing left
    r"\bbard(?:aa|a)sht nahi ho raha\b",       # can't bear it
    r"\bbard(?:aa|a)sht nahi hoti\b",
    r"\bhaar (?:gaya|gayi|maan) (?:gaya|gayi)?\s?(?:hun|hoon)?\b",  # I've given up
    r"\bhimmat (?:toot|tut) (?:gayi|gaya)\b",  # spirit broken
    r"\b(?:bohot|bahut) (?:pareshan|dukhi|udaas|akela|akeli)\b",   # very distressed/alone
    r"\btut (?:gaya|gayi|chuka|chuki) (?:hun|hoon)\b",             # I'm broken
    r"\bbekaar hun\b",                         # I'm worthless
    r"\bbekar (?:hun|hoon)\b",
    r"\bkuch samajh nahi aa raha\b",           # completely lost/overwhelmed
    r"\brona (?:aa raha|nahi ruk)",            # can't stop crying
]

_STRONG_AMBER_RE = _compile(_STRONG_AMBER)
_STRONG_AMBER_HINGLISH_RE = _compile(_STRONG_AMBER_HINGLISH)
_MILD_AMBER_RE = _compile(_MILD_AMBER)


def _strong_amber_hit(norm: str) -> bool:
    if any(rx.search(norm) for rx in _STRONG_AMBER_RE):
        return True
    return any(rx.search(norm) for rx in _STRONG_AMBER_HINGLISH_RE)


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


def assess(text: str, recent_risk: object = None, now: datetime | None = None) -> TriageResult:
    """``triage`` wrapped in the :class:`TriageResult` the LLM entrypoint requires."""
    return TriageResult(tier=triage(text, recent_risk=recent_risk, now=now), night=_is_night(now))


def red_category(text: str) -> str:
    """Grade a RED message as ``"explicit"`` or ``"passive"`` — used ONLY by the graded
    crisis register (G4). It does not change triage: the message is already RED. It only
    distinguishes active/volitional ideation, means, plan, or harm-to-others ("explicit")
    from a passive death-wish with no method or intent ("passive", e.g. "don't want to be
    here", "jeena nahi chahta"). Explicit is the default when a hit can't be graded, so
    the full crisis card (the safest surface) is what an ambiguous RED gets.
    """
    norm = _normalize(text)
    variants = _variants(norm)

    # Explicit wins if ANY active/means/plan/harm pattern matches.
    for v in variants:
        for rx in _RED_CORE_RE:
            for m in rx.finditer(v):
                # honor denial suppression, consistent with _red_hit
                if not any(ds <= m.start() and de >= m.end()
                           for ds, de in (mm.span() for mm in _DENIAL_RE.finditer(v))):
                    return "explicit"
        if any(rx.search(v) for rx in _RED_HARM_OTHERS_RE):
            return "explicit"
    if _slang_hit(norm):
        return "explicit"
    if any(rx.search(norm) for rx in _RED_HINGLISH_EXPLICIT_RE):
        return "explicit"
    if not _DENIAL_RE.search(norm):
        collapsed = _collapsed(norm)
        _explicit_collapsed = {t for t in _COLLAPSED_RED
                               if t not in {"dontwanttobehere", "dontwanttobealive",
                                            "dontwanttoliveanymore", "betteroffdead",
                                            "wishiwasdead"}}
        if any(t in collapsed for t in _explicit_collapsed):
            return "explicit"

    # Passive death-wish (English or Hinglish) with no active component above.
    if any(rx.search(norm) for rx in _RED_PASSIVE_EN):
        return "passive"
    if any(rx.search(norm) for rx in _RED_HINGLISH_PASSIVE_RE):
        return "passive"

    # RED but couldn't be graded -> treat as explicit (full card, the safest surface).
    return "explicit"
