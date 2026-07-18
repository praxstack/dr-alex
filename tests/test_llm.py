"""LLM integration: graceful degradation and prompt assembly (subprocess mocked)."""

from __future__ import annotations

import subprocess
import types

import pytest

from dr_alex import llm
from safety.triage import Tier


def _msgs(text: str = "hi") -> list[llm.Message]:
    return [llm.Message(role="user", content=text)]


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def test_env_override_for_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(llm.CLAUDE_BIN_ENV, "/custom/claude")
    assert llm.claude_bin() == "/custom/claude"
    assert llm.claude_available() is True


def test_missing_binary_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(llm.CLAUDE_BIN_ENV, raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda _name: None)
    assert llm.claude_available() is False


# ---------------------------------------------------------------------------
# generate(): never raises; degrades to a calm fallback.
# ---------------------------------------------------------------------------


def test_generate_when_claude_missing_is_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(llm.CLAUDE_BIN_ENV, raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda _name: None)

    result = llm.generate(_msgs(), Tier.GREEN, system_prompt="sys")
    assert result.ok is False
    assert result.used_fallback is True
    assert result.tier is Tier.GREEN
    # The fallback is calm and points to help — never a crash or a raw traceback.
    assert "F1" in result.text or "Shreya" in result.text


def test_generate_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(llm.CLAUDE_BIN_ENV, "/fake/claude")

    def fake_run(cmd, **kwargs):
        assert "/fake/claude" in cmd[0]
        assert "--append-system-prompt" in cmd
        return _fake_completed(stdout="  Hey Prax, I'm here.  \n")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    result = llm.generate(_msgs(), Tier.AMBER, system_prompt="sys")
    assert result.ok is True
    assert result.text == "Hey Prax, I'm here."
    assert result.tier is Tier.AMBER


def test_generate_nonzero_exit_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(llm.CLAUDE_BIN_ENV, "/fake/claude")
    monkeypatch.setattr(
        llm.subprocess, "run",
        lambda cmd, **kw: _fake_completed(stdout="", stderr="boom", returncode=1),
    )
    result = llm.generate(_msgs(), Tier.GREEN, system_prompt="sys")
    assert result.ok is False
    assert result.used_fallback is True
    assert result.error == "boom"


def test_generate_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(llm.CLAUDE_BIN_ENV, "/fake/claude")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    result = llm.generate(_msgs(), Tier.GREEN, system_prompt="sys", timeout=1)
    assert result.ok is False
    assert result.used_fallback is True
    assert "timed out" in (result.error or "")


def test_generate_missing_binary_at_run_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # Binary reported present but vanishes at exec time (FileNotFoundError).
    monkeypatch.setenv(llm.CLAUDE_BIN_ENV, "/fake/claude")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    result = llm.generate(_msgs(), Tier.GREEN, system_prompt="sys")
    assert result.used_fallback is True


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_system_prompt_includes_persona_and_continuity() -> None:
    sp = llm.build_system_prompt("PERSONA-BODY", "CONTINUITY-BODY")
    assert "PERSONA-BODY" in sp
    assert "CONTINUITY-BODY" in sp
    assert "CONTINUITY_BRIEF" in sp


def test_prompt_carries_safety_state_tier() -> None:
    p_green = llm.build_prompt(_msgs("hello"), Tier.GREEN)
    assert '<SAFETY_STATE tier="GREEN">' in p_green
    assert "Prax: hello" in p_green

    p_amber = llm.build_prompt(_msgs("i feel low"), Tier.AMBER)
    assert '<SAFETY_STATE tier="AMBER">' in p_amber
    # AMBER injects a grounding-first instruction.
    assert "grounding" in p_amber.lower()


# ---------------------------------------------------------------------------
# stream(): always yields something, even with no binary.
# ---------------------------------------------------------------------------


def test_stream_without_binary_yields_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(llm.CLAUDE_BIN_ENV, raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda _name: None)
    chunks = list(llm.stream(_msgs(), Tier.GREEN, system_prompt="sys"))
    assert chunks
    assert any("Shreya" in c or "F1" in c for c in chunks)
