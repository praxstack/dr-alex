"""G17 crisis prescreen — the debounce BYPASS so safety never waits on latency.

The G17 debounce buffer coalesces rapid inbound fragments over a short window before running
one considered turn. That is a fine latency/UX trade for ordinary chatter, but it must NEVER
delay a crisis: a fragment that reads as acute distress has to reach triage + the crisis card
*immediately*, with zero added wait.

This module is that fast-path. It reuses the **single deterministic triage lexicon**
(:mod:`safety.triage`) as the source of truth — there is no second, drifting crisis
vocabulary here. If :func:`safety.triage.triage` would classify a fragment RED, the debounce
buffer flushes it now. False positives are harmless (they just run the safety turn a few
seconds sooner); a false negative here is not a crisis-miss (the full triage still runs at
flush time on the coalesced text). The bias, as everywhere in the safety spine, is to caution.
"""

from __future__ import annotations

from safety.triage import Tier, triage


def is_crisis(text: str) -> bool:
    """True iff the deterministic triage would classify ``text`` RED (bypass-eligible).

    Reuses the exact RED lexicon (English + Hinglish + obfuscation handling) so the prescreen
    can never diverge from the real gate.
    """
    if not text or not text.strip():
        return False
    return triage(text) is Tier.RED


def should_bypass_debounce(text: str) -> tuple[bool, str | None]:
    """Return ``(bypass, reason)``. ``(True, "crisis")`` ⇒ flush the buffer NOW.

    The reason tag is only ever used in body-free operational logs (no raw text).
    """
    if is_crisis(text):
        return True, "crisis"
    return False, None
