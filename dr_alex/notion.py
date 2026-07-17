"""The Notion mirror — a thin, typed ``httpx`` client (council D2/D4).

This is deliberately NOT a Notion MCP server: a small, auditable HTTP client is a much
smaller attack surface than a general-purpose MCP tool that could be steered. It mirrors two
databases — **Sessions** and **Homework** — and nothing else.

Secrets discipline (Directive 2, binding):
  * The Notion **token** and the two **database IDs** live ONLY in the macOS Keychain (python
    ``keyring``, service ``"dr-alex"``). The model NEVER sees the token or the DB IDs — they
    are read at runtime, here, and never injected into any prompt, log, or URL.
  * When the token is absent the mirror is gracefully **DISABLED**: every entry point returns a
    disabled result and nothing is sent. Prax provisions the secrets himself (the one-liners
    are in ``config.toml`` and the report); this code never handles a raw token.

Privacy dial (``notion_detail_level``): ``summary`` (default) | ``structured`` | ``full``. A
**raw transcript is NEVER mirrored at any level.** A **RED**-tier session is always forced down
to ``summary`` and flagged *reviewed offline*.

Idempotency: the stable ULID ``session_id`` is the key. The mirror stores the returned
``page_id`` in ``state.db`` so a re-run PATCHes the same page (query→PATCH-if-exists /
create-if-not). Re-running a session end is safe.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import keyring

from dr_alex import config, crypto
from dr_alex.digest import SessionDigest

_log = logging.getLogger("dr_alex.notion")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Keychain accounts (service is crypto.SERVICE == "dr-alex").
TOKEN_ACCOUNT = "notion-token"
SESSIONS_DB_ACCOUNT = "notion-db-sessions"
HOMEWORK_DB_ACCOUNT = "notion-db-homework"

#: Kill-switch: with this set the mirror is DISABLED regardless of the Keychain. The test suite
#: sets it by default (belt-and-suspenders) so no test can ever reach the real Notion API.
_NOTION_OFF_ENV = "DR_ALEX_NOTION_OFF"

_TIMEOUT = 15.0


def _notion_off() -> bool:
    return os.environ.get(_NOTION_OFF_ENV, "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Config (from Keychain only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotionConfig:
    token: str
    sessions_db: str | None
    homework_db: str | None


def load_notion_config() -> NotionConfig | None:
    """Read the token + DB ids from Keychain. ``None`` (⇒ disabled) when the token is absent."""
    if _notion_off():
        return None
    try:
        token = keyring.get_password(crypto.SERVICE, TOKEN_ACCOUNT)
    except Exception:  # noqa: BLE001 — a Keychain hiccup disables the mirror, never crashes
        return None
    if not token:
        return None
    try:
        sessions_db = keyring.get_password(crypto.SERVICE, SESSIONS_DB_ACCOUNT)
        homework_db = keyring.get_password(crypto.SERVICE, HOMEWORK_DB_ACCOUNT)
    except Exception:  # noqa: BLE001
        sessions_db = homework_db = None
    return NotionConfig(token=token, sessions_db=sessions_db, homework_db=homework_db)


def is_enabled() -> bool:
    """True only when a Notion token is provisioned in the Keychain."""
    return load_notion_config() is not None


# ---------------------------------------------------------------------------
# Property builders + the privacy dial (redaction)
# ---------------------------------------------------------------------------


def _title(value: str) -> dict:
    return {"title": [{"text": {"content": value[:1900]}}]}


def _rt(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value[:1900]}}]}


def _num(value):
    return {"number": value}


def _select(name: str) -> dict:
    return {"select": {"name": name[:100]}}


def _multi(names: list[str]) -> dict:
    return {"multi_select": [{"name": n[:100]} for n in names[:20]]}


def _date(iso: str) -> dict:
    return {"date": {"start": iso}}


def _checkbox(value: bool) -> dict:
    return {"checkbox": bool(value)}


def effective_detail_level(tier: str, detail_level: str | None) -> tuple[str, bool]:
    """Resolve the level actually used + whether this is a RED forced-summary case.

    RED sessions are ALWAYS forced to ``summary`` regardless of the configured dial.
    """
    level = detail_level or config.notion_detail_level()
    if level not in config.VALID_NOTION_DETAIL_LEVELS:
        level = "summary"
    if (tier or "").upper() == "RED":
        return "summary", True
    return level, False


def _full_summary_paragraph(digest: SessionDigest) -> str:
    """A deterministic, self-report-free recap paragraph (``full`` level only).

    Composed strictly from already-structured digest fields — NEVER the raw transcript.
    """
    bits: list[str] = []
    if digest.key_insight:
        bits.append(digest.key_insight.strip().rstrip("."))
    if digest.techniques:
        bits.append("Techniques: " + ", ".join(
            f"{t.name} ({t.efficacy})" for t in digest.techniques))
    if digest.threads_open:
        bits.append("Still open: " + "; ".join(digest.threads_open))
    return ". ".join(bits) + "." if bits else "No structured recap available for this session."


def session_properties(
    digest: SessionDigest, *, tier: str, detail_level: str | None = None,
) -> dict:
    """Build the redacted Notion property payload for a session (RAW TRANSCRIPT NEVER).

    ``summary`` (default): session id, date, risk, mood in/out, technique NAMES, one-line
    insight. ``structured`` adds open/closed thread titles + homework titles. ``full`` adds a
    deterministic recap paragraph. RED is forced to ``summary`` + ``Reviewed Offline``.
    """
    level, red_forced = effective_detail_level(tier, detail_level)

    props: dict = {
        "Session": _title(digest.session_id),
        "Date": _date(digest.ended_at),
        "Risk": _select(digest.risk_tier_max or "GREEN"),
        "Detail Level": _select(level),
        "Reviewed Offline": _checkbox(red_forced),
    }
    if digest.mood_in is not None:
        props["Mood In"] = _num(digest.mood_in)
    if digest.mood_out is not None:
        props["Mood Out"] = _num(digest.mood_out)
    if digest.techniques:
        props["Techniques"] = _multi([t.name for t in digest.techniques])
    if digest.key_insight:
        props["Insight"] = _rt(digest.key_insight)
    if digest.generation_failed:
        props["Insight"] = _rt("⚠ distillation failed — reviewed from raw state.db")

    # summary stops here: NO threads, NO homework, NO transcript, NO verbatim.
    if level in ("structured", "full"):
        if digest.threads_open:
            props["Threads Open"] = _rt("; ".join(digest.threads_open))
        if digest.threads_closed:
            props["Threads Closed"] = _rt("; ".join(digest.threads_closed))
        if digest.homework_assigned:
            props["Homework"] = _rt("; ".join(digest.homework_assigned))
    if level == "full":
        props["Summary"] = _rt(_full_summary_paragraph(digest))

    return props


def homework_properties(title: str, *, status: str, assigned_date: str, session_id: str) -> dict:
    return {
        "Task": _title(title),
        "Status": _select(status),
        "Assigned": _date(assigned_date) if assigned_date else _rt(""),
        "Session": _rt(session_id),
    }


# ---------------------------------------------------------------------------
# The thin HTTP client
# ---------------------------------------------------------------------------


class NotionError(RuntimeError):
    """A Notion API call failed (network / non-2xx). Callers degrade gracefully."""


class NotionClient:
    """Minimal typed client: query-by-session_id, create page, update page.

    Accepts an injected ``httpx.Client`` so tests drive it with ``httpx.MockTransport`` and
    never touch the network. The token is set as a bearer header and is NEVER logged (R3).
    """

    def __init__(self, cfg: NotionConfig, *, http=None) -> None:
        self._cfg = cfg
        if http is not None:
            self._http = http
            self._owns_http = False
        else:
            import httpx

            # Absolute URLs are built per-call (see below), so no base_url is needed — this
            # avoids RFC-3986 base-join surprises that would silently drop the ``/v1`` prefix.
            self._http = httpx.Client(
                headers={
                    "Authorization": f"Bearer {cfg.token}",
                    "Notion-Version": NOTION_VERSION,
                    "Content-Type": "application/json",
                },
                timeout=_TIMEOUT,
            )
            self._owns_http = True

    def close(self) -> None:
        if self._owns_http:
            try:
                self._http.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "NotionClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- primitives -------------------------------------------------------

    def _json(self, resp) -> dict:
        if resp.status_code >= 300:
            # Never include the response body verbatim in the exception message — keep it to a
            # status code (R3: no content in logs / tracebacks).
            raise NotionError(f"notion API returned HTTP {resp.status_code}")
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise NotionError("notion API returned non-JSON") from exc
        return data if isinstance(data, dict) else {}

    def query_by_session_id(self, database_id: str, session_id: str) -> str | None:
        """Return the page_id of the row whose ``Session`` title equals ``session_id``, else None."""
        body = {
            "filter": {"property": "Session", "title": {"equals": session_id}},
            "page_size": 1,
        }
        data = self._json(self._http.post(f"{NOTION_API}/databases/{database_id}/query", json=body))
        results = data.get("results") or []
        if results and isinstance(results[0], dict):
            pid = results[0].get("id")
            return pid if isinstance(pid, str) else None
        return None

    def create_page(self, database_id: str, properties: dict) -> str:
        body = {"parent": {"database_id": database_id}, "properties": properties}
        data = self._json(self._http.post(f"{NOTION_API}/pages", json=body))
        pid = data.get("id")
        if not isinstance(pid, str):
            raise NotionError("notion create returned no page id")
        return pid

    def update_page(self, page_id: str, properties: dict) -> str:
        data = self._json(self._http.patch(f"{NOTION_API}/pages/{page_id}", json={"properties": properties}))
        pid = data.get("id")
        return pid if isinstance(pid, str) else page_id


# ---------------------------------------------------------------------------
# Orchestration — the idempotent upsert
# ---------------------------------------------------------------------------


@dataclass
class MirrorResult:
    ok: bool
    disabled: bool = False
    page_id: str | None = None
    op: str | None = None  # "create" | "patch"
    detail_level: str | None = None
    reviewed_offline: bool = False
    homework_synced: int = 0
    error: str | None = None


def _upsert(
    client: NotionClient, *, database_id: str, session_id: str, db_kind: str,
    properties: dict, path=None,
) -> tuple[str, str]:
    """Query→PATCH-if-exists / create-if-not. Returns (page_id, op). Idempotent by session_id."""
    from dr_alex import statedb

    known = statedb.get_notion_page_id(session_id, db_kind, path=path)
    if known:
        page_id = client.update_page(known, properties)
        statedb.set_notion_page_id(session_id, db_kind, page_id, path=path)
        return page_id, "patch"

    queried = client.query_by_session_id(database_id, session_id)
    if queried:
        page_id = client.update_page(queried, properties)
        statedb.set_notion_page_id(session_id, db_kind, page_id, path=path)
        return page_id, "patch"

    page_id = client.create_page(database_id, properties)
    statedb.set_notion_page_id(session_id, db_kind, page_id, path=path)
    return page_id, "create"


def mirror_session(
    digest: SessionDigest,
    *,
    tier: str | None = None,
    detail_level: str | None = None,
    client: NotionClient | None = None,
    path=None,
) -> MirrorResult:
    """Mirror one finished session to Notion (idempotent, graceful-disabled, redacted).

    ``tier`` defaults to the digest's ``risk_tier_max``. A RED session is forced to
    ``summary`` + ``reviewed offline``. Never raises: any failure returns ``ok=False`` with an
    error string so session-end never breaks on the mirror.
    """
    tier = (tier or digest.risk_tier_max or "GREEN").upper()
    cfg = None
    owns_client = False
    try:
        cfg = load_notion_config()
        if cfg is None:
            return MirrorResult(ok=False, disabled=True)
        if not cfg.sessions_db:
            return MirrorResult(ok=False, disabled=True,
                                error="sessions database id not provisioned")

        if client is None:
            client = NotionClient(cfg)
            owns_client = True

        level, red_forced = effective_detail_level(tier, detail_level)
        props = session_properties(digest, tier=tier, detail_level=detail_level)
        page_id, op = _upsert(
            client, database_id=cfg.sessions_db, session_id=digest.session_id,
            db_kind="sessions", properties=props, path=path,
        )

        return MirrorResult(
            ok=True, page_id=page_id, op=op, detail_level=level, reviewed_offline=red_forced,
        )
    except NotionError as exc:
        _log.warning("notion mirror failed: %s", exc)
        return MirrorResult(ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — the mirror must never break session end
        _log.warning("notion mirror error: %s", type(exc).__name__)
        return MirrorResult(ok=False, error=type(exc).__name__)
    finally:
        if owns_client and client is not None:
            client.close()
