"""Offline containment checks; no real credentials, model or clinical data."""

import json
import os
from pathlib import Path
import sys
import types

from dr_alex import subscription_backend as backend


def test_invalid_input_never_initializes_transport(monkeypatch):
    monkeypatch.setattr(backend, "_run", lambda *a: (_ for _ in ()).throw(AssertionError()))
    for value in (None, {}, {"system_prompt": "x", "prompt": "x", "model": "other"}):
        assert backend.complete_payload(value)["error_code"] == "invalid_request"


def test_environment_is_sterile_and_restored_even_on_failure(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", "/never-read-clinical-profile")
    monkeypatch.setenv("HERMES_DUMP_REQUEST_STDOUT", "1")
    previous = dict(os.environ)
    cwd = Path.cwd()

    def run(payload, canonical, scratch):
        assert Path.home() == scratch == Path.cwd()
        assert os.environ["HERMES_HOME"] == str(scratch)
        assert "HERMES_DUMP_REQUEST_STDOUT" not in os.environ
        assert [p.name for p in scratch.iterdir()] == ["config.yaml"]
        assert "PRIVATE_MARKER" not in (scratch / "config.yaml").read_text()
        print("PRIVATE_MARKER")
        raise RuntimeError("PRIVATE_MARKER")

    monkeypatch.setattr(backend, "_run", run)
    result = backend.complete_payload({"system_prompt": "PRIVATE_MARKER", "prompt": "hello"})
    assert result == {"ok": False, "text": "", "error_code": "provider_unavailable"}
    assert dict(os.environ) == previous
    assert Path.cwd() == cwd


def test_native_auth_scope_zero_tools_and_exact_supplied_context(monkeypatch, tmp_path):
    state = {"home": tmp_path, "resolves": []}
    canonical = tmp_path / "canonical"

    def set_home(home):
        previous = state["home"]
        state["home"] = home
        return previous

    def resolve(**kwargs):
        state["resolves"].append(state["home"])
        return {"api_key": "synthetic", "base_url": "https://example.invalid"}

    class Agent:
        def __init__(self, **kwargs):
            state["options"] = kwargs
            self.tools = []
            self._memory_enabled = False

        def _try_refresh_codex_client_credentials(self, **kwargs):
            resolve(**kwargs)
            return True

        def _build_api_kwargs(self, *a, **k):
            return {"tools": []}

        def run_conversation(self, prompt, conversation_history):
            assert self._build_api_kwargs()["tools"] == []
            import pytest

            with pytest.raises(PermissionError):
                (tmp_path / "request_dump.json").write_text(prompt)
            assert self._persist_disabled and not self._session_json_enabled
            assert self._cached_system_prompt == "SUPPLIED_SYSTEM"
            assert self._build_system_prompt() == "SUPPLIED_SYSTEM"
            assert self._dump_api_request_debug({"prompt": prompt}) is None
            assert prompt == "SUPPLIED_USER" and conversation_history == []
            assert self._try_refresh_codex_client_credentials(force=True)
            assert state["home"] == tmp_path
            return {"completed": True, "final_response": "OK"}

        def close(self):
            state["closed"] = True

    monkeypatch.setitem(
        sys.modules,
        "hermes_constants",
        types.SimpleNamespace(
            set_hermes_home_override=set_home, reset_hermes_home_override=set_home
        ),
    )
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.auth",
        types.SimpleNamespace(resolve_codex_runtime_credentials=resolve),
    )
    monkeypatch.setitem(sys.modules, "run_agent", types.SimpleNamespace(AIAgent=Agent))
    assert (
        backend._run(
            {"system_prompt": "SUPPLIED_SYSTEM", "prompt": "SUPPLIED_USER"}, canonical, tmp_path
        )
        == "OK"
    )
    assert state["resolves"] == [canonical, canonical]
    assert state["options"]["enabled_toolsets"] == []
    assert state["options"]["fallback_model"] == []
    assert state["options"]["session_db"] is None
    assert state["options"]["skip_memory"] and state["options"]["skip_context_files"]
    assert state["closed"]
