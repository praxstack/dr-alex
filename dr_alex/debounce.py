"""G17 debounce/coalesce — fold rapid inbound fragments into one considered turn.

People in distress (and ADHD/depression more specifically — the council's stated user)
often send a thought in bursts: three quick fragments in five seconds rather than one tidy
paragraph. Running a full safety-first turn on each fragment is wasteful and, worse, reads
as three separate replies to what was one thought. This buffer coalesces fragments that
arrive within a short window (~4s) into a single ``\\n``-joined message, then flushes once.

The load-bearing exception is safety: a fragment that the crisis prescreen
(:mod:`safety.crisis_prescreen`) reads as acute distress **bypasses** the window and flushes
immediately — safety never waits on latency. Caps (fragment count / bytes / age) also force
an early flush so the buffer can't be used to stall or balloon.

Adapted from the Hermes graft-pack ``debounce.py``: same council-locked constants and the
Clock/Scheduler injection seams (so tests drive it with a FrozenClock + FakeScheduler and
never sleep), simplified for Dr. Alex's local, single-user, no-Telegram world. Body-free
telemetry only (R3): flush logs carry counts + a reason, never fragment text.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Protocol

logger = logging.getLogger("dr_alex.debounce")

# Council-locked constants (graft-pack conv b6ce8ec8).
WINDOW_SECONDS: Final[float] = 4.0
MAX_FRAGMENTS: Final[int] = 50
MAX_BYTES: Final[int] = 200_000
MAX_AGE_SECONDS: Final[float] = 30.0


# ---------------------------------------------------------------------------
# Injection seams (so tests never sleep).
# ---------------------------------------------------------------------------


class Clock(Protocol):
    def now(self) -> float:  # pragma: no cover - protocol
        ...


class Scheduler(Protocol):
    def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> object:  # pragma: no cover
        ...

    def cancel(self, handle: object) -> None:  # pragma: no cover
        ...


class _SystemClock:
    def now(self) -> float:
        return _time.monotonic()


class ThreadingTimerScheduler:
    """Production scheduler backed by ``threading.Timer`` (daemon threads, idempotent cancel)."""

    def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> threading.Timer:
        timer = threading.Timer(delay_seconds, callback)
        timer.daemon = True
        timer.start()
        return timer

    def cancel(self, handle: object) -> None:
        if hasattr(handle, "cancel"):
            try:
                handle.cancel()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001 — cancellation must never crash the flush
                # A timer that would not cancel can still fire and flush a stale fragment.
                logger.warning("debounce timer cancel failed: %s", type(exc).__name__)


class FlushReason:
    TIMER: Final[str] = "timer"
    SIZE_CAP: Final[str] = "size_cap"
    BYTE_CAP: Final[str] = "byte_cap"
    AGE_CAP: Final[str] = "age_cap"
    CRISIS_BYPASS: Final[str] = "crisis_bypass"
    MANUAL: Final[str] = "manual"


@dataclass(frozen=True)
class FlushPayload:
    """The coalesced result handed to the flush callback (already ``\\n``-joined)."""

    key: str
    text: str
    fragment_count: int
    total_bytes: int
    age_seconds: float
    reason: str


@dataclass
class _Entry:
    key: str
    fragments: list[str] = field(default_factory=list)
    first_seen_at: float = 0.0
    total_bytes: int = 0
    timer_handle: object | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class DebounceBuffer:
    """Per-key coalescing buffer with a timer flush + a crisis bypass.

    ``flush_callback`` receives one :class:`FlushPayload` per flush. It is invoked from the
    timer thread for timer flushes and from the calling thread for cap / manual / bypass
    flushes, so it must be thread-safe.
    """

    def __init__(
        self,
        *,
        flush_callback: Callable[[FlushPayload], None],
        clock: Clock | None = None,
        scheduler: Scheduler | None = None,
        window_seconds: float = WINDOW_SECONDS,
        max_fragments: int = MAX_FRAGMENTS,
        max_bytes: int = MAX_BYTES,
        max_age_seconds: float = MAX_AGE_SECONDS,
        crisis_predicate: Callable[[str], bool] | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._flush_callback = flush_callback
        self._clock: Clock = clock or _SystemClock()
        self._scheduler: Scheduler = scheduler or ThreadingTimerScheduler()
        self._window = window_seconds
        self._max_fragments = max_fragments
        self._max_bytes = max_bytes
        self._max_age = max_age_seconds
        # Default crisis predicate reuses the deterministic triage lexicon (single source of
        # truth). Imported lazily so this module has no import cycle with safety.
        if crisis_predicate is None:
            from safety.crisis_prescreen import is_crisis as crisis_predicate  # noqa: N806
        self._is_crisis = crisis_predicate
        self._buffers: dict[str, _Entry] = {}
        self._dict_lock = threading.Lock()

    # -- public API -------------------------------------------------------

    def push(self, key: str, text: str) -> FlushPayload | None:
        """Append ``text`` under ``key``. Returns a :class:`FlushPayload` if this push forced
        an immediate flush (crisis bypass or a cap), else ``None`` (the timer will flush).

        A crisis fragment bypasses the window entirely: the whole buffer (prior fragments +
        this one) flushes NOW, so triage + the crisis card run with zero added latency.
        """
        if not text:
            return None
        now = self._clock.now()
        with self._dict_lock:
            entry = self._buffers.get(key)
            if entry is None:
                entry = _Entry(key=key, first_seen_at=now)
                self._buffers[key] = entry

        with entry.lock:
            text_bytes = len(text.encode("utf-8"))

            # Crisis bypass — flush the whole buffer immediately (safety never waits).
            if self._is_crisis(text):
                entry.fragments.append(text)
                entry.total_bytes += text_bytes
                payload = self._build_payload(entry, FlushReason.CRISIS_BYPASS)
                self._finish(key, entry)
                return payload

            # Caps: flush what we have, then seed the next buffer with this fragment.
            reason = None
            if entry.fragments and len(entry.fragments) >= self._max_fragments:
                reason = FlushReason.SIZE_CAP
            elif entry.fragments and entry.total_bytes + text_bytes > self._max_bytes:
                reason = FlushReason.BYTE_CAP
            elif entry.fragments and (now - entry.first_seen_at) >= self._max_age:
                reason = FlushReason.AGE_CAP
            if reason is not None:
                self._fire(entry, reason)
                entry.fragments = [text]
                entry.total_bytes = text_bytes
                entry.first_seen_at = now
                self._reschedule(entry)
                return None

            # Normal append + (re)schedule the window timer.
            if not entry.fragments:
                entry.first_seen_at = now
            entry.fragments.append(text)
            entry.total_bytes += text_bytes
            self._reschedule(entry)
            return None

    def flush_now(self, key: str, *, reason: str = FlushReason.MANUAL) -> FlushPayload | None:
        """Force-flush ``key`` immediately (used when the client marks a fragment final).

        Returns the coalesced payload WITHOUT firing the callback (the caller owns delivery),
        or ``None`` if the buffer is empty.
        """
        with self._dict_lock:
            entry = self._buffers.get(key)
        if entry is None:
            return None
        with entry.lock:
            if not entry.fragments:
                self._finish(key, entry)
                return None
            payload = self._build_payload(entry, reason)
            self._finish(key, entry)
            return payload

    def pending_count(self) -> int:
        with self._dict_lock:
            return sum(1 for e in self._buffers.values() if e.fragments)

    def cancel_all(self) -> None:
        with self._dict_lock:
            entries = list(self._buffers.items())
            self._buffers.clear()
        for _key, entry in entries:
            with entry.lock:
                if entry.timer_handle is not None:
                    self._scheduler.cancel(entry.timer_handle)
                    entry.timer_handle = None

    # -- internals (entry.lock held unless noted) -------------------------

    def _build_payload(self, entry: _Entry, reason: str) -> FlushPayload:
        n = len(entry.fragments)
        joined = "\n".join(entry.fragments)
        age = self._clock.now() - entry.first_seen_at
        logger.info(
            "buffer_flush key=%s fragments=%d bytes=%d reason=%s",
            entry.key, n, entry.total_bytes, reason,
        )
        return FlushPayload(
            key=entry.key, text=joined, fragment_count=n,
            total_bytes=entry.total_bytes, age_seconds=age, reason=reason,
        )

    def _fire(self, entry: _Entry, reason: str) -> None:
        """Build the payload and invoke the flush callback. Caller holds entry.lock."""
        if not entry.fragments:
            return
        payload = self._build_payload(entry, reason)
        if entry.timer_handle is not None:
            self._scheduler.cancel(entry.timer_handle)
            entry.timer_handle = None
        try:
            self._flush_callback(payload)
        except Exception as exc:  # noqa: BLE001 — a callback crash must not corrupt buffer state
            logger.error("flush_callback raised %s; buffer reset anyway", type(exc).__name__)

    def _finish(self, key: str, entry: _Entry) -> None:
        """Cancel the timer, clear the entry, and drop it from the dict. Caller holds entry.lock."""
        if entry.timer_handle is not None:
            self._scheduler.cancel(entry.timer_handle)
            entry.timer_handle = None
        entry.fragments = []
        entry.total_bytes = 0
        entry.first_seen_at = 0.0
        with self._dict_lock:
            self._buffers.pop(key, None)

    def _reschedule(self, entry: _Entry) -> None:
        if entry.timer_handle is not None:
            self._scheduler.cancel(entry.timer_handle)
        key = entry.key

        def _fire_timer() -> None:
            self._on_timer(key)

        entry.timer_handle = self._scheduler.schedule(self._window, _fire_timer)

    def _on_timer(self, key: str) -> None:
        with self._dict_lock:
            entry = self._buffers.get(key)
        if entry is None:
            return
        with entry.lock:
            if not entry.fragments:
                return
            self._fire(entry, FlushReason.TIMER)
            self._finish(key, entry)
