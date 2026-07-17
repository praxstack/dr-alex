"""Proactive nightly check-in (council D5) — a gentle, DISABLED-by-default nudge.

A launchd LaunchAgent (``tools/launchd/com.prax.dralex-checkin.plist``, shipped ``Disabled``)
runs ``dr-alex checkin --notify`` at 21:30 by default. That does two safe things:

  1. Posts a **macOS local notification** via ``osascript`` whose body is a **FIXED LITERAL
     string** — council D5 rider, binding: **NO interpolation of mood / streak / session / any
     therapy data.** A lock screen is semi-public, so the notification must never leak a word
     of clinical content, and it is never safety-critical (no crisis routing here).
  2. Drops a tiny ``pending`` flag so the next time Prax opens the TUI it shows a gentle
     "there was a check-in nudge" banner (the actual invitation happens inside the app, gated
     by triage like everything else).

Enablement is the gardener pattern: nothing is loaded until Prax runs the one documented
command (see the plist header). ``ntfy`` is noted there as the Phase-5 / Tailscale-era upgrade.

R3: the pending-flag file holds only two timestamps + a boolean — never message content.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("dr_alex.checkin")

# ---- The FIXED notification strings (council D5 rider — NO interpolation, ever) ----
FIXED_NOTIFICATION_TITLE = "Dr. Alex"
FIXED_NOTIFICATION_BODY = "Evening check-in whenever you're ready — no agenda."

# The banner the TUI shows on the next open after a nudge (also fixed / non-clinical).
NEXT_OPEN_BANNER = "There was an evening check-in nudge earlier. No pressure — I'm here when you want."

_DEFAULT_HOUR = 21
_DEFAULT_MINUTE = 30

_STATE_ENV = "DR_ALEX_CHECKIN_STATE"


def notification_title() -> str:
    return FIXED_NOTIFICATION_TITLE


def notification_body() -> str:
    """The one and only notification body. Takes NO arguments by design (nothing to interpolate)."""
    return FIXED_NOTIFICATION_BODY


# ---------------------------------------------------------------------------
# Pending-flag state (two timestamps + a bool; never any content)
# ---------------------------------------------------------------------------


def state_path() -> Path:
    override = os.environ.get(_STATE_ENV)
    if override:
        return Path(override)
    from dr_alex import paths

    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / "checkin.json"


@dataclass
class CheckinState:
    pending: bool = False
    last_notified_ts: str | None = None
    last_cleared_ts: str | None = None


def _load(path: Path | None = None) -> CheckinState:
    p = path or state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return CheckinState()
    if not isinstance(data, dict):
        return CheckinState()
    return CheckinState(
        pending=bool(data.get("pending", False)),
        last_notified_ts=data.get("last_notified_ts"),
        last_cleared_ts=data.get("last_cleared_ts"),
    )


def _save(state: CheckinState, path: Path | None = None) -> None:
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".checkin.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({
                "pending": state.pending,
                "last_notified_ts": state.last_notified_ts,
                "last_cleared_ts": state.last_cleared_ts,
            }, fh)
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def mark_pending(*, now: _dt.datetime | None = None, path: Path | None = None) -> None:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    st = _load(path)
    st.pending = True
    st.last_notified_ts = _iso(now)
    _save(st, path)


def pending_banner(*, path: Path | None = None) -> str | None:
    """The fixed next-open banner text if a nudge is pending, else None."""
    return NEXT_OPEN_BANNER if _load(path).pending else None


def clear_pending(*, now: _dt.datetime | None = None, path: Path | None = None) -> None:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    st = _load(path)
    if not st.pending:
        return
    st.pending = False
    st.last_cleared_ts = _iso(now)
    _save(st, path)


# ---------------------------------------------------------------------------
# The notification (osascript) — best-effort, injectable, never raises
# ---------------------------------------------------------------------------


def _osascript_args(title: str, body: str) -> list[str]:
    # AppleScript `display notification "<body>" with title "<title>"`. Both strings are the
    # fixed constants above; nothing is interpolated from telemetry. ``ensure_ascii=False`` keeps
    # UTF-8 (e.g. an em-dash) literal — AppleScript double-quoted strings don't understand
    # ``\uXXXX`` escapes, and JSON's ``"``/``\`` escaping matches AppleScript's, so this yields a
    # valid, readable string literal.
    q_body = json.dumps(body, ensure_ascii=False)
    q_title = json.dumps(title, ensure_ascii=False)
    script = f"display notification {q_body} with title {q_title}"
    return ["osascript", "-e", script]


def _default_runner(args: list[str]) -> int:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=10)
        return proc.returncode
    except Exception:  # noqa: BLE001 — a notification failure is never fatal
        return 1


def post_notification(*, runner=None) -> bool:
    """Post the FIXED local notification. Returns True on a 0 exit. Never raises.

    The body/title come ONLY from the fixed constants (D5). ``runner`` is injectable so tests
    capture the exact argv without spawning ``osascript``.
    """
    args = _osascript_args(FIXED_NOTIFICATION_TITLE, FIXED_NOTIFICATION_BODY)
    run = runner or _default_runner
    try:
        return run(args) == 0
    except Exception:  # noqa: BLE001
        return False


def run_checkin_notify(
    *, now: _dt.datetime | None = None, runner=None, path: Path | None = None,
) -> bool:
    """The launchd entrypoint: post the fixed notification + mark the next-open banner pending.

    Best-effort and never safety-critical. Returns whether the notification posted.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    posted = post_notification(runner=runner)
    try:
        mark_pending(now=now, path=path)
    except Exception:  # noqa: BLE001
        pass
    return posted


# ---------------------------------------------------------------------------
# launchd plist helpers
# ---------------------------------------------------------------------------

PLIST_LABEL = "com.prax.dralex-checkin"


def plist_relpath() -> str:
    return f"tools/launchd/{PLIST_LABEL}.plist"


def render_plist(*, hour: int = _DEFAULT_HOUR, minute: int = _DEFAULT_MINUTE) -> str:
    """Render the DISABLED-by-default LaunchAgent (gardener enable pattern)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Dr. Alex nightly check-in — DISABLED BY DEFAULT (council D5, gardener enable pattern).

  Shipped intentionally inert: `Disabled` is true and it is NOT loaded. At {hour:02d}:{minute:02d}
  it runs `dr-alex checkin --notify`, which posts a macOS local notification with a FIXED,
  non-interpolated body ("{FIXED_NOTIFICATION_BODY}") and drops a next-open TUI banner flag.
  It is NEVER safety-critical and never carries any therapy data (a lock screen is semi-public —
  council D5 rider). ntfy is the Phase-5 / Tailscale-era upgrade for phone delivery.

  To ENABLE (one command — you, deliberately):
      cp {plist_relpath()} ~/Library/LaunchAgents/ \\
        && launchctl load -w ~/Library/LaunchAgents/{PLIST_LABEL}.plist

  To DISABLE again:
      launchctl unload -w ~/Library/LaunchAgents/{PLIST_LABEL}.plist

  Edit ProgramArguments to your installed `dr-alex` path and WorkingDirectory to your checkout
  before enabling.
-->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>

    <key>Disabled</key>
    <true/>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-lc</string>
        <string>dr-alex checkin --notify</string>
    </array>

    <key>WorkingDirectory</key>
    <string>REPLACE_WITH_YOUR/dr-alex</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def _iso(now: _dt.datetime) -> str:
    dt = now.astimezone(_dt.timezone.utc) if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
