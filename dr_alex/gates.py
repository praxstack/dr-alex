"""Deterministic output gates — the last check before a reply reaches Prax (STEP 5).

Two code-level gates, both pure and un-prompt-injectable:

1. **Citation validator.** Every ``[B#]`` in the reply must resolve to a chunk that was
   *actually retrieved this turn*. Unresolvable/fabricated labels are stripped and the
   claim they propped up is softened (a confident "research shows …" opener becomes a
   humble one). PAGE NUMBERS ARE BANNED from output — sources have none, so any page
   reference is a fabrication and is removed. (Council D1 rider.)

2. **Anti-dependency lint.** A deterministic scan for dependency framing ("I'm always
   here", "your best friend", "I'm all you need", "you don't need anyone else"). On a hit
   the model gets ONE corrective regeneration; if it *still* trips the lint, the reply is
   deterministically replaced with a fixed boundary-respecting line that points Prax back
   to Shreya and real people. (Option-1 graft.)

Order matters: the anti-dependency lint runs first (it can replace the whole reply), then
the survivor is citation-validated.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Citation validation
# ---------------------------------------------------------------------------

# A citation "group": [B1], [B1, B2], [B1 and B3], [B1/B2], etc.
_GROUP = re.compile(r"\[\s*B\d+(?:\s*(?:,|and|;|/|&)\s*B?\d+)*\s*\]", re.IGNORECASE)

# A confident-authority phrase that a fabricated cite props up. When the citation is
# stripped, this opener is softened so the sentence no longer poses as sourced fact.
_AUTH_SOFT = re.compile(
    r"(?:research|studies|the research|the studies|the literature|evidence|science)\s+"
    r"(?:show[s]?|say[s]?|state[s]?|confirm[s]?|prove[s]?|suggest[s]?|demonstrate[s]?|"
    r"indicate[s]?|find[s]?)\s+(?:that\s+)?",
    re.IGNORECASE,
)

# Page references — none of the sources have pages, so any is fabricated.
_PAGE_RE = re.compile(
    r"\(?\s*\b(?:pp?|pgs?|pages?)\.?\s*\d+(?:\s*[-–—]\s*\d+)?\s*\)?",
    re.IGNORECASE,
)

# Split into sentence-ish segments, keeping the delimiters so formatting is preserved.
_SENTENCE_SPLIT = re.compile(r'([.!?]["\')\]]?\s+)')

_SOFTEN = "Some people find that "


@dataclass
class CitationResult:
    text: str
    stripped: list[str] = field(default_factory=list)  # fabricated labels removed
    page_stripped: bool = False


def _tidy(text: str) -> str:
    text = re.sub(r"\(\s*\)", "", text)          # empty parens left by a strip
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)  # space before punctuation
    text = re.sub(r"[ \t]{2,}", " ", text)        # runs of spaces (not newlines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


def _process_segment(seg: str, valid: set[int]) -> tuple[str, list[str]]:
    """Trim fabricated labels from one sentence; soften it if it lost its only source."""
    stripped: list[str] = []
    kept_any = False
    fabricated = False

    def repl(m: re.Match[str]) -> str:
        nonlocal kept_any, fabricated
        nums = [int(x) for x in re.findall(r"\d+", m.group(0))]
        kept = [n for n in nums if n in valid]
        for n in nums:
            if n not in valid:
                stripped.append(f"B{n}")
                fabricated = True
        if kept:
            kept_any = True
        return "".join(f"[B{n}]" for n in kept)  # "" when none resolve

    seg = _GROUP.sub(repl, seg)
    if fabricated and not kept_any:
        # The sentence's only citation was fabricated — soften a confident claim.
        seg = _AUTH_SOFT.sub(_SOFTEN, seg, count=1)
    return seg, stripped


def validate_citations(reply: str, retrieved: Sequence[object]) -> CitationResult:
    """Strip fabricated ``[B#]`` labels + all page numbers; soften propped-up claims.

    Valid labels are ``[B1]``..``[Bk]`` for the ``k`` chunks retrieved *this turn*; any
    other label is fabricated. Page numbers are removed wholesale.
    """
    valid = set(range(1, len(retrieved) + 1))
    text, n_pages = _PAGE_RE.subn("", reply)
    page_stripped = n_pages > 0

    stripped: list[str] = []
    out: list[str] = []
    for i, part in enumerate(_SENTENCE_SPLIT.split(text)):
        if i % 2 == 1:  # a delimiter captured by the split — leave it alone
            out.append(part)
            continue
        seg, seg_stripped = _process_segment(part, valid)
        stripped.extend(seg_stripped)
        out.append(seg)
    return CitationResult(text=_tidy("".join(out)), stripped=stripped, page_stripped=page_stripped)


# ---------------------------------------------------------------------------
# Anti-dependency lint
# ---------------------------------------------------------------------------

_DEP_PATTERNS = (
    r"i'?m always here",
    r"i am always here",
    r"i'?ll always be here",
    r"i will always be here",
    r"always here for you",
    r"i'?m always going to be here",
    r"i'?m your best friend",
    r"your best friend",
    r"you'?re my best friend",
    r"my best friend",
    r"i'?m all you need",
    r"all you need is me",
    r"you don'?t need anyone else",
    r"you don'?t need anybody else",
    r"you don'?t need anyone but me",
    r"don'?t need anyone but me",
    r"i'?ll never leave you",
    r"i will never leave you",
    r"i'?ll never leave",
    r"i'?m here for you 24[\s/]?7",
    r"i'?m the only one who",
    r"i'?m the only one you",
    r"you can always count on me",
    r"i'?m always available",
    r"lean on me instead",
)
_DEP_RE = tuple(re.compile(p) for p in _DEP_PATTERNS)

_CORRECTIVE = (
    "IMPORTANT: your previous reply used dependency language that positions you as Prax's "
    "primary relationship or an always-available substitute for people. Rewrite it. Remove "
    'any "I\'m always here / your best friend / I\'m all you need / you don\'t need anyone '
    'else" framing. You are support BETWEEN sessions, not a replacement. Warmly point Prax '
    "toward one real person (Shreya, his brother Sachin, Ishani) or his own next step. Keep "
    "the warmth; drop the dependency."
)

# The deterministic fallback if regeneration still trips the lint. Must itself be clean.
_BOUNDARY_LINE = (
    "I'm really glad you reached out. I want to be honest, though: I'm support between "
    "your sessions with Shreya — not a stand-in for the people in your life. That's on "
    "purpose. Who's one real person you could reach today — Shreya, Sachin, or Ishani?"
)


@dataclass
class BoundaryResult:
    text: str
    action: str  # "clean" | "regenerated" | "replaced"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


def has_dependency_language(text: str) -> bool:
    n = _norm(text)
    return any(rx.search(n) for rx in _DEP_RE)


def enforce_boundaries(
    reply: str, *, regenerate: Callable[[str], str | None]
) -> BoundaryResult:
    """Lint for dependency framing; regenerate once; else replace deterministically."""
    if not has_dependency_language(reply):
        return BoundaryResult(reply, "clean")

    regen = regenerate(_CORRECTIVE)  # exactly one corrective regeneration
    if regen and regen.strip() and not has_dependency_language(regen):
        return BoundaryResult(regen.strip(), "regenerated")

    return BoundaryResult(_BOUNDARY_LINE, "replaced")


# ---------------------------------------------------------------------------
# Combined gate
# ---------------------------------------------------------------------------


@dataclass
class GateOutcome:
    text: str
    dependency_action: str = "clean"
    stripped_cites: list[str] = field(default_factory=list)
    page_stripped: bool = False


def apply(
    reply: str,
    retrieved: Sequence[object],
    *,
    regenerate: Callable[[str], str | None],
) -> GateOutcome:
    """Run both gates in order: anti-dependency lint, then citation validation."""
    boundary = enforce_boundaries(reply, regenerate=regenerate)
    cites = validate_citations(boundary.text, retrieved)
    return GateOutcome(
        text=cites.text,
        dependency_action=boundary.action,
        stripped_cites=cites.stripped,
        page_stripped=cites.page_stripped,
    )
