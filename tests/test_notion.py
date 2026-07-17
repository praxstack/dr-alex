"""The Notion mirror — MOCKED httpx only (never a real API call).

Covers the four council-required cases: graceful-disabled, idempotent upsert (create then
patch the SAME page_id), summary-dial redaction (no transcript / verbatim / thread leaks), and
RED → forced summary + reviewed-offline.
"""

from __future__ import annotations

import datetime as _dt
import json

import httpx
import keyring
import pytest

from dr_alex import notion, statedb
from dr_alex.digest import SessionDigest, Technique

_UTC = _dt.timezone.utc

_CANARY_THREAD = "CANARYTHREAD-late-night-contact-loop"
_CANARY_HW = "CANARYHW-message-the-ex"
_CANARY_INSIGHT = "one-line insight is allowed at summary"


def _digest(**over) -> SessionDigest:
    base = dict(
        session_id="01SESSNOTION", started_at="2026-07-18T08:00:00Z",
        ended_at="2026-07-18T09:00:00Z", risk_tier_max="GREEN",
        mood_in=4, mood_out=6,
        techniques=[Technique("behavioral-activation", "helped")],
        threads_open=[_CANARY_THREAD], homework_assigned=[_CANARY_HW],
        key_insight=_CANARY_INSIGHT,
    )
    base.update(over)
    return SessionDigest(**base)


@pytest.fixture()
def notion_enabled(monkeypatch):
    """Provision the Keychain token + DB ids and lift the kill-switch; clean up after."""
    monkeypatch.delenv("DR_ALEX_NOTION_OFF", raising=False)
    keyring.set_password(notion.crypto.SERVICE, notion.TOKEN_ACCOUNT, "secret_test_token")
    keyring.set_password(notion.crypto.SERVICE, notion.SESSIONS_DB_ACCOUNT, "DB_SESSIONS")
    keyring.set_password(notion.crypto.SERVICE, notion.HOMEWORK_DB_ACCOUNT, "DB_HOMEWORK")
    yield
    for acct in (notion.TOKEN_ACCOUNT, notion.SESSIONS_DB_ACCOUNT, notion.HOMEWORK_DB_ACCOUNT):
        keyring.delete_password(notion.crypto.SERVICE, acct)


class _MockNotion:
    """A stand-in Notion API over httpx.MockTransport. Records every request."""

    def __init__(self, *, existing_page: str | None = None) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.existing_page = existing_page
        self._page_seq = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, request.url.path, body))
        path = request.url.path
        if path.endswith("/query"):
            results = [{"id": self.existing_page}] if self.existing_page else []
            return httpx.Response(200, json={"results": results})
        if path == "/v1/pages":
            self._page_seq += 1
            return httpx.Response(200, json={"id": f"PAGE{self._page_seq}"})
        if path.startswith("/v1/pages/"):
            page_id = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"id": page_id})
        return httpx.Response(404, json={})

    def client(self) -> notion.NotionClient:
        cfg = notion.load_notion_config()
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        return notion.NotionClient(cfg, http=http)


# ---------------------------------------------------------------------------
# 1. graceful-disabled
# ---------------------------------------------------------------------------


def test_mirror_is_gracefully_disabled_without_a_token() -> None:
    # The suite defaults DR_ALEX_NOTION_OFF=1; is_enabled must be False and nothing is sent.
    assert notion.is_enabled() is False
    res = notion.mirror_session(_digest())
    assert res.ok is False and res.disabled is True
    assert res.page_id is None


def test_kill_switch_disables_even_with_a_token(notion_enabled, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_NOTION_OFF", "1")
    assert notion.is_enabled() is False
    assert notion.mirror_session(_digest()).disabled is True


# ---------------------------------------------------------------------------
# 2. idempotent upsert — create then patch the SAME page_id
# ---------------------------------------------------------------------------


def test_idempotent_upsert_creates_then_patches_same_page(notion_enabled) -> None:
    mock = _MockNotion()  # no existing page → first run creates
    client = mock.client()

    r1 = notion.mirror_session(_digest(), client=client)
    assert r1.ok and r1.op == "create" and r1.page_id == "PAGE1"

    # Re-run the SAME session: the stored page_id short-circuits to a PATCH of PAGE1 (no query,
    # no second create).
    r2 = notion.mirror_session(_digest(), client=client)
    assert r2.ok and r2.op == "patch" and r2.page_id == "PAGE1"

    methods = [(m, p) for (m, p, _b) in mock.requests]
    assert ("POST", "/v1/pages") in methods                # exactly one create
    assert methods.count(("POST", "/v1/pages")) == 1
    assert ("PATCH", "/v1/pages/PAGE1") in methods         # the patch hit the same page
    # The idempotency key is persisted in state.db.
    assert statedb.get_notion_page_id("01SESSNOTION", "sessions") == "PAGE1"


def test_existing_remote_page_is_patched_not_duplicated(notion_enabled) -> None:
    # state.db has no mapping yet, but the row already exists in Notion → query finds it → PATCH.
    mock = _MockNotion(existing_page="REMOTE9")
    client = mock.client()
    r = notion.mirror_session(_digest(), client=client)
    assert r.ok and r.op == "patch" and r.page_id == "REMOTE9"
    methods = [(m, p) for (m, p, _b) in mock.requests]
    assert ("POST", "/v1/pages") not in methods  # never created a duplicate


# ---------------------------------------------------------------------------
# 3. summary-dial redaction — no transcript / verbatim / thread leaks
# ---------------------------------------------------------------------------


def test_summary_dial_redacts_threads_and_homework() -> None:
    props = notion.session_properties(_digest(), tier="GREEN", detail_level="summary")
    blob = json.dumps(props)
    # summary keeps the one-line insight + technique names + mood…
    assert _CANARY_INSIGHT in blob
    assert "behavioral-activation" in blob
    # …but leaks NO thread titles, NO homework, NO transcript/verbatim.
    assert _CANARY_THREAD not in blob
    assert _CANARY_HW not in blob
    assert "Threads Open" not in props and "Homework" not in props and "Summary" not in props


def test_structured_dial_includes_threads_and_homework() -> None:
    props = notion.session_properties(_digest(), tier="GREEN", detail_level="structured")
    blob = json.dumps(props)
    assert _CANARY_THREAD in blob
    assert _CANARY_HW in blob


def test_full_dial_adds_summary_paragraph_but_never_a_transcript() -> None:
    props = notion.session_properties(_digest(), tier="GREEN", detail_level="full")
    assert "Summary" in props
    # The recap is composed from structured fields only — still no raw transcript concept exists.
    blob = json.dumps(props)
    assert _CANARY_INSIGHT in blob


# ---------------------------------------------------------------------------
# 4. RED → forced summary + reviewed-offline
# ---------------------------------------------------------------------------


def test_red_session_is_forced_to_summary_even_with_full_dial() -> None:
    props = notion.session_properties(_digest(risk_tier_max="RED"), tier="RED", detail_level="full")
    blob = json.dumps(props)
    # Forced down to summary: no threads, no homework, no summary paragraph.
    assert _CANARY_THREAD not in blob
    assert _CANARY_HW not in blob
    assert "Threads Open" not in props and "Summary" not in props
    # Flagged reviewed-offline + detail level recorded as summary.
    assert props["Reviewed Offline"] == {"checkbox": True}
    assert props["Detail Level"] == {"select": {"name": "summary"}}


def test_red_mirror_reports_reviewed_offline(notion_enabled) -> None:
    mock = _MockNotion()
    res = notion.mirror_session(_digest(risk_tier_max="RED"), client=mock.client())
    assert res.ok and res.detail_level == "summary" and res.reviewed_offline is True


def test_effective_detail_level_forces_summary_on_red() -> None:
    assert notion.effective_detail_level("GREEN", "full") == ("full", False)
    assert notion.effective_detail_level("RED", "full") == ("summary", True)
    assert notion.effective_detail_level("GREEN", None)[0] == "summary"  # config default
