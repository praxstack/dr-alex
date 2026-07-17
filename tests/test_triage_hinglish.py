"""Hinglish / code-mixed crisis lexicon (G2) — golden fixtures per phrase.

Romanized Hindi-English suicidal-ideation and acute-distress phrasings, written from
clinical/linguistic knowledge (NOT mined from anyone's logs). Same bias as the English
matrix: a false-negative RED is unacceptable, so every SI phrase must classify RED —
while romanized fragments living inside innocent English words ("mar" ⊂ smart/market,
"jaan" as endearment, "khatam" = "finished") must NOT fire. Every RED phrase carries a
near-miss GREEN counterpart to prove the word boundaries hold.
"""

from __future__ import annotations

import pytest

from safety.triage import Tier, red_category, triage

# ---------------------------------------------------------------------------
# RED — romanized SI. Each entry: (phrase, expected red_category).
# ---------------------------------------------------------------------------

HINGLISH_RED = [
    # want to die / kill self (marna, explicit volition)
    ("marna chahta hun", "explicit"),
    ("mujhe marna hai", "explicit"),
    ("bas ab marna chahti hun", "explicit"),
    ("marne ka mann kar raha hai", "explicit"),
    ("mar jana chahta hun ab", "explicit"),
    # reflexive: end/kill myself
    ("khud ko khatam kar dunga", "explicit"),
    ("apne aap ko maar dunga", "explicit"),
    ("khud ko maar dalna hai", "explicit"),
    # suicide nouns
    ("khudkushi karna chahta hun", "explicit"),
    ("aatmahatya ke baare mein soch raha hun", "explicit"),
    # give up my life
    ("jaan de dunga ab", "explicit"),
    ("apni jaan de dungi", "explicit"),
    # better off dead
    ("mar jana behtar hai", "explicit"),
    ("marna behtar hoga", "explicit"),
    # mixed register (English frame + romanized verb)
    ("I just want to marna", "explicit"),
    # passive death-wish (jeena / zinda)
    ("jeena nahi chahta", "passive"),
    ("mujhe nahi jeena", "passive"),
    ("jeene ka mann nahi hai", "passive"),
    ("ab aur nahi jee sakta", "passive"),
    ("zinda nahi rehna", "passive"),
    ("zinda rehne ka mann nahi", "passive"),
]


@pytest.mark.parametrize("phrase,kind", HINGLISH_RED)
def test_hinglish_si_classifies_red(phrase: str, kind: str) -> None:
    assert triage(phrase) is Tier.RED, f"Hinglish SI must be RED: {phrase!r}"


@pytest.mark.parametrize("phrase,kind", HINGLISH_RED)
def test_hinglish_red_category(phrase: str, kind: str) -> None:
    assert red_category(phrase) == kind, f"wrong graded kind for {phrase!r}"


# ---------------------------------------------------------------------------
# GREEN near-misses — innocent words/idioms that CONTAIN the romanized fragments
# or use the ambiguous words ("khatam" = finished, "jaan" = endearment) benignly.
# These must NOT fire (word-boundary + construction discipline).
# ---------------------------------------------------------------------------

HINGLISH_GREEN_NEARMISS = [
    "smart analysis of the market today",   # 'mar' ⊂ smart/market
    "the summary looks good",               # 'mar' ⊂ summary
    "marmalade on my toast",                # 'mar' ⊂ marmalade
    "Amar is a good friend",                # 'mar' ⊂ Amar (name)
    "meri jaan tum kaise ho",               # 'jaan' as endearment
    "in jeans I feel comfortable",          # 'jee' ⊂ jeans
    "karma always comes back",              # 'mar' ⊂ karma
    "movie khatam ho gayi finally",         # 'khatam' = the film ended
    "kaam khatam ho gaya aaj",              # 'khatam' = work finished
    "padh padh ke mar jaunga yaar",         # hyperbole: "I'll die from studying"
    "thoda pareshan hun bas, ho jayega",    # mild worry (not 'bohot pareshan')
]


@pytest.mark.parametrize("phrase", HINGLISH_GREEN_NEARMISS)
def test_hinglish_nearmiss_stays_green(phrase: str) -> None:
    assert triage(phrase) is Tier.GREEN, f"innocent phrase wrongly flagged: {phrase!r}"


# ---------------------------------------------------------------------------
# AMBER — romanized acute distress without SI.
# ---------------------------------------------------------------------------

HINGLISH_AMBER = [
    "bohot pareshan hun aaj kal",
    "koi ummeed nahi bachi",
    "bardaasht nahi ho raha ab",
    "kuch nahi bacha meri zindagi mein",
    "haar gaya hun main puri tarah",
    "himmat toot gayi hai",
    "main bilkul bekaar hun",
]


@pytest.mark.parametrize("phrase", HINGLISH_AMBER)
def test_hinglish_distress_classifies_amber(phrase: str) -> None:
    assert triage(phrase) is Tier.AMBER, f"Hinglish distress must be AMBER: {phrase!r}"


# ---------------------------------------------------------------------------
# The passive-ideation gap this pass closes (English), documented in the Fable-5
# re-validation: "don't want to live" (bare) was a false-negative (GREEN). It is now
# RED — but circumstance/housing continuations must NOT be swept in.
# ---------------------------------------------------------------------------

def test_bare_dont_want_to_live_is_red_passive() -> None:
    assert triage("I don't want to live") is Tier.RED
    assert red_category("I don't want to live") == "passive"


@pytest.mark.parametrize("phrase", [
    "I don't want to live in this city anymore",   # housing
    "I don't want to live with my parents",        # relational
    "I don't want to live like this",              # circumstance -> AMBER, not RED
    "I don't want to live near the airport",       # locational
])
def test_circumstantial_dont_want_to_live_is_not_red(phrase: str) -> None:
    assert triage(phrase) is not Tier.RED, f"circumstance despair wrongly RED: {phrase!r}"
