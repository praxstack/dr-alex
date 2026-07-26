"""alexd health watchdog: FIXED notification body, one alert per outage, grace-window silence.

The whole point of this module is that it must NEVER produce a false alarm at 3am, so most of
these tests assert SILENCE.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from dr_alex import health

_UTC = _dt.timezone.utc


@pytest.fixture(autouse=True)
def _throwaway_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DR_ALEX_HEALTH_STATE", str(tmp_path / "health.json"))
    # Machine has been up a long time by default, so boot grace is not what's under test.
    monkeypatch.setattr(health, "_boot_time", lambda: 0.0)


def _at(minutes: float) -> _dt.datetime:
    return _dt.datetime(2026, 7, 26, 3, 0, tzinfo=_UTC) + _dt.timedelta(minutes=minutes)


class _Notifier:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(args)
        return 0


def _down():
    return False


def _up():
    return True


# ---------------------------------------------------------------------------
# D5 rider: the notification body is a FIXED LITERAL — no interpolation, ever.
# ---------------------------------------------------------------------------


def test_down_body_is_a_fixed_literal_with_no_clinical_tokens() -> None:
    assert health.notification_body() == health.FIXED_DOWN_BODY
    assert health.notification_body() == "The Room isn't running right now."
    low = health.FIXED_DOWN_BODY.lower()
    for token in ("{", "}", "%s", "mood", "streak", "session", "shreya", "8787", "127.0.0.1"):
        assert token not in low


def test_notification_argv_carries_only_the_fixed_strings() -> None:
    notifier = _Notifier()
    assert health.post_down_notification(runner=notifier) is True
    argv = notifier.calls[0]
    assert argv[0] == "osascript"
    script = argv[-1]
    assert health.FIXED_DOWN_BODY in script
    assert health.FIXED_DOWN_TITLE in script
    for leak in ("mood", "streak", "session", "Shreya", "8787", "traceback", "Error"):
        assert leak not in script


def test_post_notification_never_raises_on_runner_failure() -> None:
    def _boom(_args):
        raise RuntimeError("osascript missing")
    assert health.post_down_notification(runner=_boom) is False


# ---------------------------------------------------------------------------
# The latch: exactly ONE notification per outage, silent recovery.
# ---------------------------------------------------------------------------


def test_exactly_one_notification_across_many_consecutive_down_probes() -> None:
    notifier = _Notifier()
    # First poll seeds last_probe_ts (wake grace can't be evaluated without a previous probe).
    health.run_health_check(now=_at(0), prober=_down, runner=notifier)
    results = [
        health.run_health_check(now=_at(5 * i), prober=_down, runner=notifier)
        for i in range(1, 8)
    ]
    assert len(notifier.calls) == 1, "an outage must alert once, never once per poll"
    assert [r["notified"] for r in results].count(True) == 1
    assert results[-1]["reason"] == "already-notified"


def test_recovery_is_silent_and_rearms_the_latch() -> None:
    notifier = _Notifier()
    health.run_health_check(now=_at(0), prober=_down, runner=notifier)
    health.run_health_check(now=_at(5), prober=_down, runner=notifier)
    assert len(notifier.calls) == 1

    # Recovery says NOTHING — nothing here ever wakes him to report good news.
    res = health.run_health_check(now=_at(10), prober=_up, runner=notifier)
    assert res["up"] is True and res["notified"] is False
    assert len(notifier.calls) == 1

    # …but a NEW outage can alert again.
    health.run_health_check(now=_at(15), prober=_down, runner=notifier)
    health.run_health_check(now=_at(20), prober=_down, runner=notifier)
    assert len(notifier.calls) == 2


def test_a_single_failed_probe_never_alerts() -> None:
    notifier = _Notifier()
    health.run_health_check(now=_at(0), prober=_down, runner=notifier)
    res = health.run_health_check(now=_at(5), prober=_up, runner=notifier)
    assert res["up"] is True
    assert notifier.calls == [], "one miss is a restart bind race, not an outage"


# ---------------------------------------------------------------------------
# Grace windows — every one of these must be SILENT.
# ---------------------------------------------------------------------------


def test_boot_grace_suppresses_everything(monkeypatch) -> None:
    notifier = _Notifier()
    # Booted 30s ago; DRALEX_BOOT_GRACE defaults to 240s. Every poll below is INSIDE that
    # window (30s..180s after boot) — polling past 240s is a different case, asserted next.
    monkeypatch.setattr(health, "_boot_time", lambda: _at(0).timestamp() - 30)
    for i in range(6):
        res = health.run_health_check(now=_at(i * 0.5), prober=_down, runner=notifier)
        assert res["reason"] == "boot-grace"
    assert notifier.calls == []


def test_boot_grace_expires_and_does_not_silence_the_watchdog_forever(monkeypatch) -> None:
    # The grace window must SUPPRESS a startup blip, not disarm the watchdog permanently.
    notifier = _Notifier()
    monkeypatch.setattr(health, "_boot_time", lambda: _at(0).timestamp() - 30)
    health.run_health_check(now=_at(0), prober=_down, runner=notifier)  # 30s after boot
    assert notifier.calls == []
    # 300s after boot: past the 240s grace, and a normal poll gap (not a wake gap).
    res = health.run_health_check(now=_at(4.5), prober=_down, runner=notifier)
    assert res["reason"] == "notified"
    assert len(notifier.calls) == 1


def test_unknowable_boot_time_fails_toward_silence(monkeypatch) -> None:
    notifier = _Notifier()
    monkeypatch.setattr(health, "_boot_time", lambda: None)
    for i in range(6):
        health.run_health_check(now=_at(i * 5), prober=_down, runner=notifier)
    assert notifier.calls == [], "if we cannot tell, we say nothing"


def test_wake_gap_suppresses_the_first_probe_after_sleep() -> None:
    notifier = _Notifier()
    health.run_health_check(now=_at(0), prober=_down, runner=notifier)
    # The Mac slept for two hours: the poll interval was skipped, so this is settling.
    res = health.run_health_check(now=_at(120), prober=_down, runner=notifier)
    assert res["reason"] == "wake-grace"
    assert notifier.calls == []
    # The NEXT normal-interval poll is not suppressed.
    res = health.run_health_check(now=_at(125), prober=_down, runner=notifier)
    assert res["reason"] == "notified"
    assert len(notifier.calls) == 1


def test_normal_poll_interval_is_not_mistaken_for_a_wake_gap() -> None:
    # Regression guard: comparing a 300s poll interval against a 120s wake grace would make
    # EVERY gap look like a wake and silence the watchdog permanently.
    now = _at(30).timestamp()
    assert health.in_wake_grace(now - health.POLL_INTERVAL, now) is False


def test_unwritable_latch_degrades_to_silence_not_repetition(monkeypatch) -> None:
    notifier = _Notifier()
    health.run_health_check(now=_at(0), prober=_down, runner=notifier)

    def _no_write(_state, _path=None):
        raise OSError("read-only data dir")

    monkeypatch.setattr(health, "save_state", _no_write)
    reasons = [
        health.run_health_check(now=_at(5 * i), prober=_down, runner=notifier)["reason"]
        for i in range(1, 6)
    ]
    # The load-bearing property is SILENCE, not any particular label.
    assert notifier.calls == [], "a watchdog that cannot remember it spoke must not speak"
    # The first post-seed poll proves the latch-unwritable path itself is what suppresses.
    assert reasons[0] == "latch-unwritable"
    # Later polls stay silent for a second, compounding reason: an unwritable latch also
    # freezes last_probe_ts, so every subsequent gap looks like a sleep gap. Both paths are
    # silent, which is the documented degradation — an unwritable latch disarms the watchdog
    # rather than letting it repeat. Repetition at 3am is the worse failure.
    assert set(reasons) <= {"latch-unwritable", "wake-grace"}, reasons


# ---------------------------------------------------------------------------
# The probe + the shipped plist
# ---------------------------------------------------------------------------


def test_probe_treats_any_failure_as_down() -> None:
    # Nothing listens on this port; the probe must return False, not raise.
    assert health.probe(timeout=0.25, url="http://127.0.0.1:1/healthz") is False


def test_shipped_plist_is_disabled_and_matches_the_poll_interval() -> None:
    p = Path(__file__).resolve().parent.parent / "tools" / "launchd" / f"{health.PLIST_LABEL}.plist"
    assert p.exists(), "the health LaunchAgent should be shipped (disabled) in tools/launchd/"
    text = p.read_text(encoding="utf-8")
    assert "<key>Disabled</key>\n\t<true/>" in text
    assert "<key>RunAtLoad</key>\n\t<false/>" in text
    assert "dr-alex health --notify" in text
    assert f"<integer>{int(health.POLL_INTERVAL)}</integer>" in text
    # The fixed body is documented in the header; no therapy data anywhere in the file.
    assert health.FIXED_DOWN_BODY in text
    # It must not touch the running daemon's restart semantics. Check for the KEY, not the
    # bare word — the header comment explains, in prose, why KeepAlive is left alone.
    assert "<key>KeepAlive</key>" not in text
    # Logs go to the app's own dir, never /tmp (which is wiped at boot).
    assert "/tmp/" not in text


def test_cli_health_never_returns_nonzero(monkeypatch) -> None:
    from dr_alex import cli

    def _explode(*_a, **_k):
        raise RuntimeError("everything is broken")

    monkeypatch.setattr(health, "run_health_check", _explode)
    monkeypatch.setattr(health, "probe", _explode)
    # A watchdog that can exit non-zero is a watchdog that can become the next crash loop.
    assert cli.main(["health", "--notify"]) == 0
    assert cli.main(["health"]) == 0
