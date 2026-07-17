"""The crisis card — India-localized crisis resources, HARD-CODED in code.

This is the single source of truth for the crisis resources. It is NEVER
model-generated. The printable ``data/crisis-card.md`` and ``data/crisis-card.txt``
files are rendered from the constants here (a test asserts they stay in sync).

Numbers verified against the architecture brief (2026-07). Re-verify periodically.
"""

from __future__ import annotations

# --- The resources. Hard-coded. Order = what to reach for first. ---------------

#: Each entry: (name, number, note). ``number`` is kept in tap-to-call friendly form.
CRISIS_RESOURCES: list[tuple[str, str, str]] = [
    (
        "Tele-MANAS",
        "14416",
        "Govt of India, 24x7, free, many languages. (Also 1800-891-4416.)",
    ),
    ("iCall (TISS)", "9152987821", "Mon-Sat, psychosocial counselling."),
    ("AASRA", "9820466726", "24x7 emotional support."),
    ("Vandrevala Foundation", "1860-2662-345", "24x7 mental health helpline."),
    ("Emergency", "112", "Immediate danger — police / ambulance."),
]

#: Prax's real therapist. Reaching a real person > any app.
THERAPIST_NAME = "Shreya"
THERAPIST_LINE = "Your therapist: Shreya — reach out to her."

#: The pre-written message Prax can send *himself* to Shreya. Never auto-sent.
SHREYA_REACH_OUT_DRAFT = (
    "Hi Shreya — I'm having a really hard time right now and could use your "
    "support. Can we talk soon?"
)

#: A short, warm grounding line shown alongside the card on a RED turn.
GROUNDING_LINE = (
    "You reached out, and that matters. Let's slow down together for a moment — "
    "you don't have to carry this alone right now."
)

#: A single-breath grounding suggestion (not a technique dump).
GROUNDING_BREATH = (
    "If you can: feet on the floor, one slow breath in for 4, out for 6. "
    "Just this one breath."
)


# --- Renderers. The card can be drawn as markdown, plain text, or Rich markup. --

_HEADER = "You don't have to be alone with this. Help is one call away."


def render_text() -> str:
    """Plain-text crisis card (for ``crisis-card.txt`` and non-Rich output)."""
    lines: list[str] = []
    lines.append("=" * 56)
    lines.append("  IF YOU ARE IN CRISIS — YOU ARE NOT ALONE")
    lines.append("=" * 56)
    lines.append("")
    lines.append(_HEADER)
    lines.append("")
    for name, number, note in CRISIS_RESOURCES:
        lines.append(f"  {name}: {number}")
        lines.append(f"      {note}")
    lines.append("")
    lines.append(f"  {THERAPIST_LINE}")
    lines.append("")
    lines.append("  A message you could send Shreya (you send it, not the app):")
    lines.append(f'    "{SHREYA_REACH_OUT_DRAFT}"')
    lines.append("")
    lines.append("  " + GROUNDING_BREATH)
    lines.append("=" * 56)
    return "\n".join(lines)


def render_markdown() -> str:
    """Markdown crisis card (for ``crisis-card.md`` and any markdown surface)."""
    lines: list[str] = []
    lines.append("## If you are in crisis — you are not alone")
    lines.append("")
    lines.append(_HEADER)
    lines.append("")
    for name, number, note in CRISIS_RESOURCES:
        lines.append(f"- **{name} — {number}**  \n  {note}")
    lines.append("")
    lines.append(f"**{THERAPIST_LINE}**")
    lines.append("")
    lines.append("_A message you could send Shreya (you send it, not the app):_")
    lines.append("")
    lines.append(f"> {SHREYA_REACH_OUT_DRAFT}")
    lines.append("")
    lines.append(GROUNDING_BREATH)
    return "\n".join(lines)


def render_rich() -> str:
    """Rich-markup crisis card for the TUI (soft, calm — not alarmist)."""
    lines: list[str] = []
    lines.append("[b]If you are in crisis — you are not alone.[/b]")
    lines.append("")
    lines.append(_HEADER)
    lines.append("")
    for name, number, note in CRISIS_RESOURCES:
        lines.append(f"  [b]{name}[/b]  [b cyan]{number}[/b cyan]")
        lines.append(f"    [dim]{note}[/dim]")
    lines.append("")
    lines.append(f"  [b]{THERAPIST_LINE}[/b]")
    lines.append("")
    lines.append("  [dim]A message you could send Shreya (you send it, not the app):[/dim]")
    lines.append(f'    [i]"{SHREYA_REACH_OUT_DRAFT}"[/i]')
    lines.append("")
    lines.append(f"  [dim]{GROUNDING_BREATH}[/dim]")
    return "\n".join(lines)


def all_numbers() -> list[str]:
    """Every phone number on the card (for tests / validation)."""
    return [number for _name, number, _note in CRISIS_RESOURCES]


# --- Graded register (G4, flag-gated) ------------------------------------------
#
# For PASSIVE ideation only (no plan/means/intent — e.g. "don't want to be here",
# "jeena nahi chahta"), and ONLY when crisis_card_style == "graded". The clinical
# lesson from the earlier production system ("never lead with hotlines" for passive hopelessness): a full
# hotline dump on passive despair reads as panic-escalation and pathologizing. This
# variant validates the feeling, stays present, nudges Shreya *today*, and keeps ONE
# always-available line (Tele-MANAS) — safety intact, register warmer. Still 100%
# deterministic, zero LLM. Explicit ideation always gets the FULL card, unchanged.

#: The single always-open line kept in the warmer variant (not the full dump).
GRADED_ALWAYS_OPEN = "And if it ever tips past this: Tele-MANAS is 14416, anytime — day or night."

GRADED_BODY = (
    "You reached out, and that matters. What you're feeling right now is heavy and "
    "real — you don't have to hold it alone, and you don't have to fix it tonight.\n\n"
    "Could you reach Shreya today? Even a short message counts, and you'd be the one "
    "to send it — not me."
)


def render_graded_text() -> str:
    """Warmer plain-text variant for passive ideation (graded register)."""
    lines = [
        GROUNDING_LINE,
        "",
        GRADED_BODY,
        "",
        "A message you could send Shreya (you send it, not the app):",
        f'    "{SHREYA_REACH_OUT_DRAFT}"',
        "",
        GRADED_ALWAYS_OPEN,
        "",
        GROUNDING_BREATH,
    ]
    return "\n".join(lines)


def render_graded_rich() -> str:
    """Warmer Rich-markup variant for passive ideation (graded register)."""
    lines = [
        f"[b]{GROUNDING_LINE}[/b]",
        "",
        GRADED_BODY,
        "",
        "[dim]A message you could send Shreya (you send it, not the app):[/dim]",
        f'    [i]"{SHREYA_REACH_OUT_DRAFT}"[/i]',
        "",
        GRADED_ALWAYS_OPEN,
        "",
        f"[dim]{GROUNDING_BREATH}[/dim]",
    ]
    return "\n".join(lines)
