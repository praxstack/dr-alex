"""Nightly check-in (council D5): FIXED notification body, pending banner, plist shape."""

from __future__ import annotations

import datetime as _dt

from dr_alex import checkin

_UTC = _dt.timezone.utc


def _now() -> _dt.datetime:
    return _dt.datetime(2026, 7, 18, 21, 30, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# D5 rider: the notification body is a FIXED LITERAL — no therapy-data interpolation.
# ---------------------------------------------------------------------------


def test_notification_body_is_a_fixed_literal_string() -> None:
    # Called any number of times, with no arguments, it returns exactly the same constant.
    assert checkin.notification_body() == checkin.FIXED_NOTIFICATION_BODY
    assert checkin.notification_body() == "Evening check-in whenever you're ready — no agenda."
    # No formatting placeholders that could ever interpolate data.
    for token in ("{", "}", "%s", "mood", "streak", "session"):
        assert token not in checkin.FIXED_NOTIFICATION_BODY.lower()


def test_post_notification_argv_carries_only_the_fixed_strings() -> None:
    captured: dict = {}

    def _runner(args):
        captured["args"] = args
        return 0

    assert checkin.post_notification(runner=_runner) is True
    argv = captured["args"]
    assert argv[0] == "osascript"
    script = argv[-1]
    # The AppleScript contains ONLY the two fixed constants — nothing else.
    assert checkin.FIXED_NOTIFICATION_BODY in script
    assert checkin.FIXED_NOTIFICATION_TITLE in script
    for leak in ("mood", "streak", "session", "9/10", "Shreya"):
        assert leak not in script


def test_post_notification_never_raises_on_runner_failure() -> None:
    def _boom(_args):
        raise RuntimeError("osascript missing")
    assert checkin.post_notification(runner=_boom) is False


# ---------------------------------------------------------------------------
# Pending next-open banner lifecycle
# ---------------------------------------------------------------------------


def test_run_checkin_notify_posts_and_marks_pending() -> None:
    seen = {"n": 0}

    def _runner(_args):
        seen["n"] += 1
        return 0

    assert checkin.pending_banner() is None
    posted = checkin.run_checkin_notify(now=_now(), runner=_runner)
    assert posted is True and seen["n"] == 1
    # A pending nudge shows the FIXED next-open banner…
    assert checkin.pending_banner() == checkin.NEXT_OPEN_BANNER
    # …and clearing it (on the next TUI open) makes it a one-shot.
    checkin.clear_pending(now=_now())
    assert checkin.pending_banner() is None


def test_next_open_banner_is_also_fixed_and_content_free() -> None:
    for leak in ("mood", "streak", "{", "}", "%s"):
        assert leak not in checkin.NEXT_OPEN_BANNER.lower()


# ---------------------------------------------------------------------------
# launchd plist — DISABLED by default, 21:30, runs the notify path
# ---------------------------------------------------------------------------


def test_plist_is_disabled_by_default_and_uses_fixed_schedule() -> None:
    xml = checkin.render_plist()
    assert "<key>Disabled</key>\n    <true/>" in xml
    assert "<key>RunAtLoad</key>\n    <false/>" in xml
    assert "dr-alex checkin --notify" in xml
    assert "<integer>21</integer>" in xml  # default hour
    assert "<integer>30</integer>" in xml  # default minute
    assert checkin.PLIST_LABEL in xml
    # The fixed body is documented in the plist header (no therapy data anywhere).
    assert checkin.FIXED_NOTIFICATION_BODY in xml


def test_shipped_plist_file_matches_disabled_convention() -> None:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "tools" / "launchd" / f"{checkin.PLIST_LABEL}.plist"
    assert p.exists(), "the check-in LaunchAgent should be shipped (disabled) in tools/launchd/"
    text = p.read_text(encoding="utf-8")
    assert "<key>Disabled</key>" in text and "<true/>" in text
    assert "dr-alex checkin --notify" in text
