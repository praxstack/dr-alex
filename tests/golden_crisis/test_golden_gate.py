"""GOLDEN CRISIS GATE (G3) — the merge fence for triage safety.

╔══════════════════════════════════════════════════════════════════════════════════╗
║  ANY change to the crisis lexicon, triage.py, the leet/normalization passes, or    ║
║  the model pins MUST keep RED sensitivity at 100% on this corpus, or the change     ║
║  DOES NOT MERGE. A missed RED is a false-negative — the one error the whole         ║
║  bias-to-caution design refuses to accept. This test is the structural guarantee    ║
║  of that invariant.                                                                 ║
╚══════════════════════════════════════════════════════════════════════════════════╝

Unlike the earlier LLM-judge gate (which needed a real C-SSRS round-trip), Dr. Alex's classifier
is deterministic, so this runs in the default unit lane on every `pytest` — no env flag,
no LLM, no tokens. The corpus (``corpus.json``) is versioned and merges: the RED/AMBER/GREEN
matrix, the Hinglish lexicon fixtures, adapted C-SSRS trigger/non-trigger cases, and
depersonalized badgering-incident phrasings.

Metrics:
  * RED sensitivity  = P(classify RED | expected RED)     — MUST be 100%.
  * specificity      = P(classify not-RED | expected not-RED) — reported; MUST be 100%
                       here (the non-RED corpus is curated circumstance-despair / benign).
  * exact-tier acc.  = pinned AMBER/GREEN cases classify to their exact tier — reported,
                       and held at 100% so the gate also fences AMBER/GREEN drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from safety.triage import Tier, triage

_CORPUS_PATH = Path(__file__).resolve().parent / "corpus.json"


def _load_cases() -> list[dict]:
    doc = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    cases = doc["cases"]
    assert cases, "golden corpus is empty"
    return cases


def _classify(text: str) -> Tier:
    return triage(text)


def test_corpus_is_versioned_and_nonempty() -> None:
    doc = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    assert doc["version"] >= 1
    assert len(doc["cases"]) >= 100  # merged corpus


def test_golden_red_sensitivity_is_100pct() -> None:
    """THE GATE: every RED-expected case MUST classify RED. 100% or it does not merge."""
    cases = _load_cases()
    red_cases = [c for c in cases if c["expected"] == "RED"]
    misses = [c for c in red_cases if _classify(c["text"]) is not Tier.RED]

    sensitivity = 1.0 - len(misses) / len(red_cases)
    print(f"\nGOLDEN GATE — RED sensitivity: {sensitivity * 100:.1f}% "
          f"({len(red_cases) - len(misses)}/{len(red_cases)})")

    assert not misses, (
        "RED SENSITIVITY < 100% — a real crisis message was missed. This blocks merge.\n"
        + "\n".join(f"  MISS [{c['source']}] {c['text']!r} -> {_classify(c['text']).value}"
                    for c in misses)
    )


def test_golden_specificity_reported_and_no_false_red() -> None:
    """Non-RED cases (benign / circumstance-despair / denials) must not false-positive RED."""
    cases = _load_cases()
    nonred = [c for c in cases if c["expected"] in ("AMBER", "GREEN", "NOT_RED")]
    false_reds = [c for c in nonred if _classify(c["text"]) is Tier.RED]

    specificity = 1.0 - len(false_reds) / len(nonred)
    print(f"GOLDEN GATE — specificity (not-RED): {specificity * 100:.1f}% "
          f"({len(nonred) - len(false_reds)}/{len(nonred)})")

    assert not false_reds, (
        "SPECIFICITY < 100% — circumstance-despair / benign text was flagged RED "
        "(the badgering false-positive class):\n"
        + "\n".join(f"  FALSE-RED [{c['source']}] {c['text']!r}" for c in false_reds)
    )


def test_golden_exact_tier_for_pinned_amber_green() -> None:
    """Pinned AMBER/GREEN cases classify to their exact tier — fences AMBER/GREEN drift."""
    cases = _load_cases()
    pinned = [c for c in cases if c["expected"] in ("AMBER", "GREEN")]
    wrong = [(c, _classify(c["text"])) for c in pinned
             if _classify(c["text"]).value != c["expected"]]

    accuracy = 1.0 - len(wrong) / len(pinned)
    print(f"GOLDEN GATE — exact-tier accuracy (pinned AMBER/GREEN): {accuracy * 100:.1f}% "
          f"({len(pinned) - len(wrong)}/{len(pinned)})")

    assert not wrong, (
        "PINNED TIER DRIFT — an AMBER/GREEN golden case changed tier:\n"
        + "\n".join(f"  [{c['source']}] {c['text']!r} expected {c['expected']} got {got.value}"
                    for c, got in wrong)
    )
