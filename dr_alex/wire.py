"""G16 wire-decision audit + empty-output guard — the delivery hardening for ``alexd``.

Two load-bearing invariants adapted from the Hermes graft-pack (``wire.py`` + ``audit.py``),
re-expressed for Dr. Alex's local, single-user, no-Telegram world:

1. **Per-turn wire-decision audit (which safety path ran).** Every ``POST /turn`` emits
   exactly ONE structured line recording {tier, safety_path_taken, chunk_ids, memory_ids}.
   This is the "no dark-launched safety" anti-pattern fix (graft-pack #2): a turn always
   records which safety path actually fired. It is body-free by construction (R3): only the
   deterministic triage tier, the safety action enum, and the *ids* of the book chunks /
   memories that grounded the turn — NEVER the message, the reply, homework titles, or any
   book/personal text. There is no user content on this line to leak.

2. **Explicit empty-output guard (no empty replies delivered).** Before a reply is streamed
   to the phone it passes through :func:`empty_output_guard`, which substitutes a calm,
   safe fallback for a blank/whitespace/"(no response)" reply. A check either BLOCKS, ALERTS
   LOUDLY, or does not exist (graft-pack anti-pattern #1 + #4) — this one blocks (replaces)
   and alerts (a WARN on the wire log, still body-free).

Neither function ever raises on the delivery path.
"""

from __future__ import annotations

import logging

from safety.triage import Tier

#: The dedicated wire-decision logger. Body-free by contract; a formatter/handler may route
#: it to a structured sink. Distinct from ``dr_alex.trace`` so the per-turn wire decision is
#: filterable on its own.
_wire_log = logging.getLogger("dr_alex.wire")

#: The calm fallback delivered instead of an empty reply (G16 empty-output guard). It never
#: claims the model said anything; it points gently at the always-available crisis surface.
EMPTY_REPLY_FALLBACK = (
    "I lost my words for a second there — that's a hiccup on my end, not anything you did. "
    "Give me a moment and say that again if you can. If things feel urgent, the "
    "“I need help right now” button up top reaches real support any time."
)


def _is_empty(text: str | None) -> bool:
    return not text or not text.strip() or text.strip() == "(no response)"


def empty_output_guard(text: str | None) -> tuple[str, bool]:
    """Return ``(safe_text, was_empty)`` — never an empty reply reaches the phone (G16).

    A blank / whitespace-only / ``"(no response)"`` reply is replaced by
    :data:`EMPTY_REPLY_FALLBACK`. The substitution is logged (WARN, body-free) so an empty
    reply is never silently swallowed.
    """
    if _is_empty(text):
        _wire_log.warning("empty_output_guard fired: substituting calm fallback")
        return EMPTY_REPLY_FALLBACK, True
    return text, False  # type: ignore[return-value]


def audit_turn(
    *,
    tier: Tier | str,
    safety_path_taken: str,
    chunk_ids: list[str] | None = None,
    memory_ids: list[str] | None = None,
    empty_guarded: bool = False,
) -> None:
    """Emit the single per-turn wire-decision line (G16). Body-free (R3); never raises.

    Records ONLY structural facts: the triage ``tier``, which ``safety_path_taken`` ran
    ("red-card", "probe-asked", "probe-suppressed", "reask-blocked", "none"), and the
    ``chunk_ids`` / ``memory_ids`` that grounded the turn. No message, reply, homework, or
    book/personal text — there is nothing on this line to leak.
    """
    try:
        tval = tier.value if isinstance(tier, Tier) else str(tier)
        _wire_log.info(
            "turn tier=%s safety=%s chunk_ids=%s memory_ids=%s empty_guarded=%s",
            tval,
            safety_path_taken or "none",
            list(chunk_ids or []),
            list(memory_ids or []),
            bool(empty_guarded),
        )
    except Exception:  # noqa: BLE001 — the audit line must never break delivery
        pass
