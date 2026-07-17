"""Claude integration — calls the `claude` CLI via subprocess.

Phase 1 keeps this deliberately thin and defensive:
- the persona (`persona/dr-alex.md`) is the system prompt;
- the continuity brief is passed as background context;
- a ``<SAFETY_STATE tier=...>`` line is always included so the model knows the
  deterministic triage verdict for the turn;
- conversation history is rendered into the prompt (print mode is stateless).

It NEVER raises on the user: a missing `claude` binary, a non-zero exit, a timeout,
or empty output all resolve to a calm fallback message. RED turns never reach here —
that short-circuit lives in the app, before this module is called.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field

from safety.triage import Tier

CLAUDE_BIN_ENV = "DR_ALEX_CLAUDE_BIN"
MODEL_ENV = "DR_ALEX_MODEL"
DEFAULT_TIMEOUT = 120

_CALM_FALLBACK = (
    "I'm having trouble reaching my words right now — the model I think with isn't "
    "responding. That's a hiccup on my end, not anything you did.\n\n"
    "If things feel urgent, please press F1 for the crisis card, or reach Shreya. "
    "Otherwise, give me a moment and try again."
)

_AMBER_GROUNDING_NOTE = (
    "Prax may be in elevated distress right now. Lead with grounding and warmth before "
    "any advice: slow down, acknowledge the feeling, and if it fits, offer one small "
    "grounding or body-awareness step. Keep it gentle and short. Gently keep a door open "
    "toward Shreya and real-world support."
)


@dataclass
class LLMResult:
    ok: bool
    text: str
    tier: Tier = Tier.GREEN
    error: str | None = None
    used_fallback: bool = False


@dataclass
class Message:
    role: str  # "user" or "assistant"
    content: str


def claude_bin() -> str | None:
    """Path to the claude CLI (env override, then PATH)."""
    override = os.environ.get(CLAUDE_BIN_ENV)
    if override:
        return override
    return shutil.which("claude")


def claude_available() -> bool:
    return claude_bin() is not None


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_system_prompt(persona: str, continuity: str | None = None) -> str:
    parts = [persona.strip()]
    if continuity:
        parts.append(
            "\n\n---\n\n<CONTINUITY_BRIEF>\n"
            "Background on Prax and where you last left off. Hold it gently; use it to be "
            "warm and specific, not to interrogate.\n\n"
            + continuity.strip()
            + "\n</CONTINUITY_BRIEF>"
        )
    return "\n".join(parts)


def _render_history(messages: list[Message]) -> str:
    lines: list[str] = []
    for m in messages:
        who = "Prax" if m.role == "user" else "Dr. Alex"
        lines.append(f"{who}: {m.content.strip()}")
    return "\n".join(lines)


def build_prompt(messages: list[Message], tier: Tier) -> str:
    """The -p prompt: a SAFETY_STATE line + the conversation so far."""
    safety_note = ""
    if tier is Tier.AMBER:
        safety_note = "\n" + _AMBER_GROUNDING_NOTE
    header = f'<SAFETY_STATE tier="{tier.value}">{safety_note}\n</SAFETY_STATE>'
    convo = _render_history(messages)
    return (
        f"{header}\n\n<CONVERSATION>\n{convo}\n</CONVERSATION>\n\n"
        "Respond as Dr. Alex to Prax's most recent message. Warm, honest, brief."
    )


def _base_cmd(system_prompt: str, output_format: str) -> list[str]:
    binary = claude_bin()
    assert binary is not None  # callers guard with claude_available()
    cmd = [binary, "-p", "--output-format", output_format,
           "--append-system-prompt", system_prompt]
    model = os.environ.get(MODEL_ENV)
    if model:
        cmd += ["--model", model]
    return cmd


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------


def generate(
    messages: list[Message],
    tier: Tier,
    *,
    system_prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> LLMResult:
    """Full (non-streaming) response. Never raises; degrades to a calm fallback."""
    if not claude_available():
        return LLMResult(
            ok=False,
            text=_CALM_FALLBACK,
            tier=tier,
            error="claude CLI not found on PATH",
            used_fallback=True,
        )

    prompt = build_prompt(messages, tier)
    cmd = _base_cmd(system_prompt, "text")
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return LLMResult(ok=False, text=_CALM_FALLBACK, tier=tier, error=str(exc), used_fallback=True)
    except subprocess.TimeoutExpired:
        return LLMResult(
            ok=False,
            text=_CALM_FALLBACK,
            tier=tier,
            error=f"claude timed out after {timeout}s",
            used_fallback=True,
        )
    except OSError as exc:  # pragma: no cover - defensive
        return LLMResult(ok=False, text=_CALM_FALLBACK, tier=tier, error=str(exc), used_fallback=True)

    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip() or f"claude exited {proc.returncode}"
        return LLMResult(ok=False, text=_CALM_FALLBACK, tier=tier, error=err, used_fallback=True)

    return LLMResult(ok=True, text=out, tier=tier)


# ---------------------------------------------------------------------------
# Streaming (best-effort; falls back to a single full chunk)
# ---------------------------------------------------------------------------


def _extract_text(obj: object) -> str:
    """Pull assistant text out of one stream-json object, best-effort."""
    if not isinstance(obj, dict):
        return ""
    # Final result event.
    if obj.get("type") == "result" and isinstance(obj.get("result"), str):
        return obj["result"]
    msg = obj.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(block.get("text", ""))
            return "".join(chunks)
    # Partial delta shapes.
    delta = obj.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("text"), str):
        return delta["text"]
    return ""


def stream(
    messages: list[Message],
    tier: Tier,
    *,
    system_prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> Iterator[str]:
    """Yield response text incrementally. Falls back to yielding the full text once.

    Guarantees at least one yield (a calm fallback if everything fails), so callers can
    render something without special-casing.
    """
    if not claude_available():
        yield _CALM_FALLBACK
        return

    prompt = build_prompt(messages, tier)
    cmd = _base_cmd(system_prompt, "stream-json") + ["--verbose"]

    emitted = 0
    got_any = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, OSError):
        # Fall back to the non-streaming path.
        result = generate(messages, tier, system_prompt=system_prompt, timeout=timeout)
        yield result.text
        return

    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
        cumulative = ""
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _extract_text(obj)
            if not text:
                continue
            got_any = True
            # Some shapes are cumulative, some are deltas. Handle both: if the new
            # text starts with what we've seen, treat as cumulative; else append.
            if text.startswith(cumulative) and len(text) >= len(cumulative):
                new = text[len(cumulative):]
                cumulative = text
            else:
                new = text
                cumulative += text
            if new:
                emitted += len(new)
                yield new
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
    except OSError:  # pragma: no cover - defensive
        proc.kill()

    if not got_any or emitted == 0:
        # Streaming produced nothing usable — fall back to full response.
        result = generate(messages, tier, system_prompt=system_prompt, timeout=timeout)
        yield result.text
