"""Fence neutralization for untrusted context channels (prompt-injection defense, D4).

Book chunks (``<BOOK_CONTEXT>``), recalled therapy memory (``<PERSONAL_MEMORY>``) and the
continuity brief (``<CONTINUITY_BRIEF>``) all flow from the corpus/store into LABELED,
fenced blocks inside the highest-authority appended-system-prompt channel. A chunk or
snippet that contains a literal fence closer (``</BOOK_CONTEXT>``) or an injection marker
("ignore previous instructions", a fake ``System:`` role header) could otherwise break out
of its fence or issue instructions.

:func:`neutralize` is pure Python (no LLM, never raises). It defangs any fence-tag token and
any injection marker BEFORE the untrusted text is placed inside a fenced block, so the block
structure the model sees is always the one WE built — corpus/memory content can be read, but
it cannot close a fence early nor pose as an instruction.
"""

from __future__ import annotations

import re

#: The fence/label tokens whose literal ``<...>`` forms must never survive inside a block.
_FENCE_TOKENS = (
    "BOOK_CONTEXT",
    "PERSONAL_MEMORY",
    "CONTINUITY_BRIEF",
    "SESSION_START",
    "SAFETY_STATE",
    "CONVERSATION",
)

# A full or partial tag: a literal '<' + optional '/', a fence token, up to an optional '>'.
_FENCE_RE = re.compile(
    r"<\s*/?\s*(?:" + "|".join(_FENCE_TOKENS) + r")\b[^>]*>?",
    re.IGNORECASE,
)

#: Instruction-shaped markers that untrusted content must not smuggle in as directives.
_INJECTION_RES = (
    re.compile(
        r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier|the\s+above)\s+"
        r"(?:instructions?|prompts?|directions?|messages?|context)",
        re.IGNORECASE,
    ),
    re.compile(
        r"disregard\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier|the)\s+"
        r"(?:instructions?|prompts?|directions?|rules?)",
        re.IGNORECASE,
    ),
    re.compile(r"forget\s+(?:everything|all|what)\s+(?:above|before|previous|you)", re.IGNORECASE),
    re.compile(r"(?:new|updated|revised)\s+(?:instructions?|system\s+prompt|directive)\s*:", re.IGNORECASE),
    # A fake role header at the start of a line ("System:", "Assistant:", "Human:", "User:").
    re.compile(r"(?m)^\s*(?:system|assistant|human|user)\s*:", re.IGNORECASE),
)

#: What a neutralized span is replaced with — visible, structure-free, non-executable.
_REDACT = "[redacted]"


def neutralize(text: str | None) -> str:
    """Return ``text`` with fence tokens and injection markers defanged (D4).

    Idempotent and total: ``None``/empty pass through unchanged; otherwise every fence-tag
    token and injection marker is replaced with a safe ``[redacted]`` placeholder. The
    returned string carries no ``<FENCE>`` delimiter and no "ignore previous instructions"
    style directive, so it can be dropped inside a labeled block without altering it.
    """
    if not text:
        return text or ""
    out = _FENCE_RE.sub(_REDACT, text)
    for rx in _INJECTION_RES:
        out = rx.sub(_REDACT, out)
    return out
