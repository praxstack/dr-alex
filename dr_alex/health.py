"""Watchdog for the always-on daemon — the health check the alexd plist already pays for.

``com.prax.dralex-alexd.plist`` exports ``DRALEX_BOOT_GRACE`` and ``DRALEX_WAKE_GRACE`` and
has done since it was written, but nothing ever read them: launchd itself only knows
``KeepAlive`` + ``ThrottleInterval``, and the grace windows were always meant for a health
check that was never built. So the daemon could die and be restarted forever with no
detection and no signal — a silent window between "broken" and "next time Prax opens it".

This module is that reader. It does NOT touch ``KeepAlive``: restarting forever is the right
behaviour on a Mac and self-heals every transient fault. It only closes the detection gap.

Design constraints, all pointing the same way — **never a false alarm at 3am**:

  * The notification body is a **FIXED LITERAL** with zero interpolation — no status, no port,
    no hostname, no session or therapy data (council D5 rider: a lock screen is semi-public).
  * Two CONSECUTIVE failed probes are required. A single miss during the 10s
    ``ThrottleInterval`` restart window is a bind race, not an outage.
  * Boot grace: nothing is said while the machine is still coming up.
  * Wake grace: a probe failure right after a sleep gap (the poll interval was skipped, so the
    Mac was asleep) is a settle case, not an outage.
  * Any error computing either grace window **fails toward silence**, never toward an alarm.
  * The latch is persisted BEFORE the notification is posted. If it cannot be persisted, we
    post nothing — degrading to silence, never to repetition.
  * Exactly ONE notification per outage, and **no recovery notification**: nothing here ever
    wakes him to say things are fine.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# ---- The FIXED notification strings (council D5 rider — NO interpolation, ever) ----
FIXED_DOWN_TITLE = "Dr. Alex"
FIXED_DOWN_BODY = "The Room isn't running right now."

#: The loopback health endpoint (the daemon is loopback-only by construction — D3 rider 1).
HEALTH_URL = "http://127.0.0.1:8787/healthz"

_BOOT_GRACE_ENV = "DRALEX_BOOT_GRACE"
_WAKE_GRACE_ENV = "DRALEX_WAKE_GRACE"
_DEFAULT_BOOT_GRACE = 240.0
_DEFAULT_WAKE_GRACE = 120.0

_STATE_ENV = "DR_ALEX_HEALTH_STATE"

#: Consecutive failed probes required before anything is said.
_DOWN_THRESHOLD = 2

#: The poll interval, in seconds — must match ``StartInterval`` in the shipped plist. Used
#: only to recognise a SKIPPED poll (a sleep gap), never to schedule anything.
POLL_INTERVAL = 300.0


def notification_title() -> str:
    return FIXED_DOWN_TITLE


def notification_body() -> str:
    """The one and only body. Takes NO arguments by design (nothing to interpolate)."""
    return FIXED_DOWN_BODY


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------


def probe(*, timeout: float = 2.0, url: str = HEALTH_URL) -> bool:
    """True iff ``/healthz`` answers 200. Any exception means down. Stdlib only, no deps.

    A 200 with ``ok:false`` still counts as UP: the daemon is answering, so it is not the
    outage this watchdog exists to catch, and a degraded subsystem is not worth a 3am alarm.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — fixed loopback URL
            return int(getattr(resp, "status", 0) or 0) == 200
    except Exception:  # noqa: BLE001 — anything at all means "not answering"
        return False


# ---------------------------------------------------------------------------
# Grace windows (both fail SAFE toward silence)
# ---------------------------------------------------------------------------


def _grace_seconds(env: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(env, "").strip() or default))
    except (TypeError, ValueError):
        return default


def boot_grace_seconds() -> float:
    return _grace_seconds(_BOOT_GRACE_ENV, _DEFAULT_BOOT_GRACE)


def wake_grace_seconds() -> float:
    return _grace_seconds(_WAKE_GRACE_ENV, _DEFAULT_WAKE_GRACE)


def _boot_time() -> float | None:
    """Unix boot time, derived in-process from the monotonic clock. None if undeterminable.

    Deliberately NOT ``sysctl -n kern.boottime``: Directive 1 is enforced statically by
    ``tests/test_single_llm_entrypoint.py``, which allows a subprocess spawn from only eight
    sanctioned functions. A watchdog is not worth widening that allowlist, and it does not need
    to — on Darwin ``CLOCK_MONOTONIC`` counts wall-clock seconds since boot (it keeps
    advancing across sleep; ``CLOCK_UPTIME_RAW`` is the one that does not), so
    ``now - CLOCK_MONOTONIC`` is the boot instant. Measured against ``kern.boottime`` on this
    machine the two agree to well under a second, which is far inside a 240s grace window.

    Elsewhere (Linux) ``CLOCK_MONOTONIC`` excludes suspend, so this UNDER-estimates uptime —
    i.e. it errs toward "still booting", which is the silent direction. That is the correct way
    to be wrong here.
    """
    try:
        return time.time() - time.clock_gettime(time.CLOCK_MONOTONIC)
    except Exception:  # noqa: BLE001 — cannot tell ⇒ caller stays silent
        return None


def in_boot_grace(now_ts: float) -> bool:
    """True while the machine is still settling after boot — and on ANY failure to tell."""
    boot = _boot_time()
    if boot is None:
        return True  # cannot tell ⇒ stay silent (never a false alarm)
    return (now_ts - boot) < boot_grace_seconds()


def in_wake_grace(last_probe_ts: float | None, now_ts: float) -> bool:
    """True when the previous poll was SKIPPED — i.e. the Mac was asleep and is settling.

    There is no portable "time since wake" API. A sleeping Mac simply misses its
    ``StartInterval`` polls, so a gap materially larger than one poll interval is exactly the
    settle case the plist's grace window describes. The comparison is against
    ``POLL_INTERVAL + wake grace`` (not the grace alone) — comparing a 300s poll interval
    against a 120s grace would make every single gap look like a wake and silence the watchdog
    permanently. A missing/unparseable previous timestamp is treated as a gap (silent).
    """
    if last_probe_ts is None:
        return True
    try:
        return (now_ts - float(last_probe_ts)) > (POLL_INTERVAL + wake_grace_seconds())
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Latch state (three numbers + a bool; never any content — R3)
# ---------------------------------------------------------------------------


def state_path() -> Path:
    override = os.environ.get(_STATE_ENV)
    if override:
        return Path(override)
    from dr_alex import paths

    found = paths.find("data")
    base = found if found is not None else (Path(__file__).resolve().parent.parent / "data")
    return base / "health.json"


@dataclass
class HealthState:
    down_since: float | None = None
    notified: bool = False
    last_probe_ts: float | None = None
    consecutive_down: int = 0


def _num(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def load_state(path: Path | None = None) -> HealthState:
    p = path or state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return HealthState()
    if not isinstance(data, dict):
        return HealthState()
    try:
        consecutive = int(data.get("consecutive_down", 0) or 0)
    except (TypeError, ValueError):
        consecutive = 0
    return HealthState(
        down_since=_num(data.get("down_since")),
        notified=bool(data.get("notified", False)),
        last_probe_ts=_num(data.get("last_probe_ts")),
        consecutive_down=max(0, consecutive),
    )


def save_state(state: HealthState, path: Path | None = None) -> None:
    """Atomically persist the latch 0600 (temp + ``os.replace``). Raises OSError on failure."""
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".health.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({
                "down_since": state.down_since,
                "notified": state.notified,
                "last_probe_ts": state.last_probe_ts,
                "consecutive_down": state.consecutive_down,
            }, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# The notification (reuses checkin's proven, injectable, never-raising runner seam)
# ---------------------------------------------------------------------------


def post_down_notification(*, runner=None) -> bool:
    """Post the FIXED down notification. Never raises. Body/title are constants only (D5)."""
    from dr_alex import checkin

    args = checkin._osascript_args(FIXED_DOWN_TITLE, FIXED_DOWN_BODY)
    run = runner or checkin._default_runner
    try:
        return run(args) == 0
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# The launchd entrypoint
# ---------------------------------------------------------------------------


def run_health_check(
    *,
    now: _dt.datetime | None = None,
    prober=None,
    runner=None,
    path: Path | None = None,
) -> dict:
    """One poll. Returns ``{"up", "notified", "reason"}``. Never raises.

    ``reason`` is one of: ``up``, ``boot-grace``, ``wake-grace``, ``below-threshold``,
    ``already-notified``, ``notified``, ``latch-unwritable``.
    """
    now_ts = (now or _dt.datetime.now(_dt.UTC)).timestamp()
    up = (prober or probe)()
    st = load_state(path)
    prev_probe_ts = st.last_probe_ts
    st.last_probe_ts = now_ts

    if up:
        # Recovery is SILENT by design — nothing here ever wakes him to say things are fine.
        st.down_since = None
        st.notified = False
        st.consecutive_down = 0
        _best_effort_save(st, path)
        return {"up": True, "notified": False, "reason": "up"}

    st.consecutive_down += 1
    if st.down_since is None:
        st.down_since = now_ts

    # --- every silent path still records the probe, so the wake gap stays measurable ---
    if in_boot_grace(now_ts):
        _best_effort_save(st, path)
        return {"up": False, "notified": False, "reason": "boot-grace"}
    if in_wake_grace(prev_probe_ts, now_ts):
        _best_effort_save(st, path)
        return {"up": False, "notified": False, "reason": "wake-grace"}
    if st.consecutive_down < _DOWN_THRESHOLD:
        _best_effort_save(st, path)
        return {"up": False, "notified": False, "reason": "below-threshold"}
    if st.notified:
        _best_effort_save(st, path)
        return {"up": False, "notified": False, "reason": "already-notified"}

    # Persist the latch BEFORE posting. If it cannot be persisted we say NOTHING: a watchdog
    # that cannot remember it already spoke would repeat every poll, and repeated 3am
    # notifications are worse than the gap this whole module exists to close.
    st.notified = True
    try:
        save_state(st, path)
    except OSError:
        return {"up": False, "notified": False, "reason": "latch-unwritable"}
    posted = post_down_notification(runner=runner)
    return {"up": False, "notified": posted, "reason": "notified"}


def _best_effort_save(state: HealthState, path: Path | None) -> None:
    try:
        save_state(state, path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# launchd plist (shipped DISABLED — the gardener enable-by-hand convention)
# ---------------------------------------------------------------------------

PLIST_LABEL = "com.prax.dralex-health"


def plist_relpath() -> str:
    return f"tools/launchd/{PLIST_LABEL}.plist"
