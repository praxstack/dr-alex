"""Private one-turn transport for llm.complete; executed in a dedicated process.

Only canonical Hermes Codex authentication is shared. Conversation state is never
shared with Hermes profiles. This module is transport, not a second clinical API.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

MODEL = "gpt-5.6-sol"
MAX_INPUT = 2_000_000


def _run(payload: dict, canonical: Path, scratch: Path) -> str:
    # Import only after HOME/config/cwd isolation. Authentication retains Hermes'
    # native shared-file locking, refresh and account-selection implementation.
    sys.path.insert(0, str(canonical / "hermes-agent"))
    from hermes_cli.auth import resolve_codex_runtime_credentials
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from run_agent import AIAgent

    @contextlib.contextmanager
    def auth_home():
        token = set_hermes_home_override(canonical)
        try:
            yield
        finally:
            reset_hermes_home_override(token)

    with auth_home():
        credentials = resolve_codex_runtime_credentials()
    if not credentials.get("api_key"):
        raise RuntimeError("auth_unavailable")
    agent = AIAgent(
        model=MODEL,
        provider="openai-codex",
        api_mode="codex_responses",
        api_key=credentials["api_key"],
        base_url=credentials["base_url"],
        enabled_toolsets=[],
        disabled_toolsets=["memory"],
        skip_context_files=True,
        load_soul_identity=False,
        skip_memory=True,
        skip_background_review=True,
        save_trajectories=False,
        verbose_logging=False,
        quiet_mode=True,
        session_db=None,
        checkpoints_enabled=False,
        max_iterations=1,
        max_tokens=4096,
        run_budget_seconds=55,
        fallback_model=[],
        platform="cli",
    )
    try:
        if agent.tools or agent._memory_enabled:
            raise RuntimeError("isolation_failed")
        agent._persist_disabled = True
        agent._session_json_enabled = False
        # Hermes otherwise adds its coding identity/environment/skills prompt and
        # writes full request dumps on provider errors, even with persistence off.
        agent._cached_system_prompt = payload["system_prompt"]
        agent._cached_system_prompt_static = payload["system_prompt"]
        agent._build_system_prompt = lambda *a, **k: payload["system_prompt"]
        agent._dump_api_request_debug = lambda *a, **k: None
        original_refresh = agent._try_refresh_codex_client_credentials

        def refresh(*args, **kwargs):
            with auth_home():
                return original_refresh(*args, **kwargs)

        agent._try_refresh_codex_client_credentials = refresh
        original_build = agent._build_api_kwargs

        def build_request(*args, **kwargs):
            request = original_build(*args, **kwargs)
            if request.get("tools"):
                raise RuntimeError("isolation_failed")
            return request

        agent._build_api_kwargs = build_request
        # Defensive disk boundary: even a newly added Hermes diagnostic cannot
        # put supplied context into the disposable runtime home. Native canonical
        # OAuth refresh remains writable under its own lock.
        writing = {"active": True}

        def disk_guard(event, args):
            if not writing["active"]:
                return
            if event == "sqlite3.connect" and str(args[0]) != ":memory:":
                raise PermissionError("transport persistence disabled")
            if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
                target = Path(os.fsdecode(args[0])).absolute()
                mode, flags = args[1], args[2]
                write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
                )
                if write and target.is_relative_to(scratch):
                    raise PermissionError("transport persistence disabled")

        sys.addaudithook(disk_guard)
        try:
            result = agent.run_conversation(payload["prompt"], conversation_history=[])
        finally:
            writing["active"] = False
        if agent.tools or agent._memory_enabled:
            raise RuntimeError("isolation_failed")
        if not result.get("completed") or not result.get("final_response"):
            raise RuntimeError("completion_failed")
        return result["final_response"]
    finally:
        agent.close()


def complete_payload(payload: object) -> dict:
    """Return a body-free failure or a single response; never expose SDK errors."""
    if (
        not isinstance(payload, dict)
        or set(payload) - {"system_prompt", "prompt", "model"}
        or any(
            not isinstance(payload.get(k), str) or not payload[k].strip()
            for k in ("system_prompt", "prompt")
        )
        or payload.get("model", MODEL) != MODEL
    ):
        return {"ok": False, "text": "", "error_code": "invalid_request"}
    canonical = Path.home() / ".hermes"
    old_env, old_cwd = dict(os.environ), Path.cwd()
    old_logging = logging.root.manager.disable
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with tempfile.TemporaryDirectory(prefix="dr-alex-transport-") as directory:
            scratch = Path(directory)
            # No prompt, SOUL, history or tokens are written to this home.
            (scratch / "config.yaml").write_text(
                json.dumps(
                    {
                        "plugins": {"enabled": []},
                        "mcp_servers": {},
                        "memory": {"memory_enabled": False, "user_profile_enabled": False},
                        "sessions": {"auto_prune": False, "write_json_snapshots": False},
                        "compression": {"enabled": False},
                        "platform_toolsets": {"cli": []},
                    }
                )
            )
            os.environ.clear()
            os.environ.update(
                {
                    "HOME": directory,
                    "HERMES_HOME": directory,
                    "HERMES_TEST_ISOLATION": directory,
                    "HERMES_IGNORE_RULES": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PATH": old_env.get("PATH", "/usr/bin:/bin"),
                    "LANG": "en_US.UTF-8",
                    "AWS_EC2_METADATA_DISABLED": "true",
                }
            )
            os.chdir(scratch)
            logging.disable(sys.maxsize)
            with (
                open(os.devnull, "w") as sink,
                contextlib.redirect_stdout(sink),
                contextlib.redirect_stderr(sink),
            ):
                text = _run(payload, canonical, scratch)
            return {"ok": True, "text": text, "error_code": None}
    except Exception:
        return {"ok": False, "text": "", "error_code": "provider_unavailable"}
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
        logging.disable(old_logging)
        sys.dont_write_bytecode = old_bytecode


def main() -> None:
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        result = (
            complete_payload(json.loads(raw))
            if len(raw) <= MAX_INPUT
            else {"ok": False, "text": "", "error_code": "invalid_request"}
        )
    except Exception:
        result = {"ok": False, "text": "", "error_code": "invalid_request"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
