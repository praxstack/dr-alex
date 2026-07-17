"""G17 debounce: coalesce rapid fragments; crisis prescreen bypasses the window; caps flush."""

from __future__ import annotations

from dr_alex import debounce


class FrozenClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeScheduler:
    """Records scheduled callbacks; the test fires them explicitly (no real threads/sleep)."""

    def __init__(self) -> None:
        self._handles: dict[int, tuple[float, callable]] = {}
        self._next = 0

    def schedule(self, delay_seconds, callback):
        h = self._next
        self._next += 1
        self._handles[h] = (delay_seconds, callback)
        return h

    def cancel(self, handle) -> None:
        self._handles.pop(handle, None)

    def fire_all(self) -> None:
        for _h, (_d, cb) in list(self._handles.items()):
            cb()


def _buffer(clock, sched, flushed, *, crisis=lambda t: False):
    return debounce.DebounceBuffer(
        flush_callback=lambda p: flushed.append(p),
        clock=clock, scheduler=sched, crisis_predicate=crisis,
    )


def test_fragments_coalesce_into_one_flush_on_timer() -> None:
    clock, sched, flushed = FrozenClock(), FakeScheduler(), []
    buf = _buffer(clock, sched, flushed)
    assert buf.push("k", "I keep") is None
    clock.advance(1.0)
    assert buf.push("k", "thinking about") is None
    clock.advance(1.0)
    assert buf.push("k", "the same thing") is None
    # No flush yet — still inside the window.
    assert flushed == []
    sched.fire_all()  # the window elapses
    assert len(flushed) == 1
    p = flushed[0]
    assert p.fragment_count == 3
    assert p.text == "I keep\nthinking about\nthe same thing"


def test_crisis_fragment_bypasses_the_window_immediately() -> None:
    clock, sched, flushed = FrozenClock(), FakeScheduler(), []
    # crisis predicate fires on the last fragment
    buf = _buffer(clock, sched, flushed, crisis=lambda t: "kill myself" in t)
    buf.push("k", "everything is heavy")
    assert flushed == []  # buffered, waiting
    payload = buf.push("k", "I want to kill myself")
    # Returned immediately (no wait) AND coalesced with the earlier fragment.
    assert payload is not None
    assert payload.reason == debounce.FlushReason.CRISIS_BYPASS
    assert payload.fragment_count == 2
    assert buf.pending_count() == 0  # buffer drained


def test_flush_now_returns_coalesced_without_firing_callback() -> None:
    clock, sched, flushed = FrozenClock(), FakeScheduler(), []
    buf = _buffer(clock, sched, flushed)
    buf.push("k", "one")
    buf.push("k", "two")
    payload = buf.flush_now("k")
    assert payload is not None and payload.text == "one\ntwo"
    assert flushed == []  # flush_now hands the payload to the caller, not the callback
    assert buf.pending_count() == 0


def test_fragment_cap_forces_early_flush() -> None:
    clock, sched, flushed = FrozenClock(), FakeScheduler(), []
    buf = debounce.DebounceBuffer(
        flush_callback=lambda p: flushed.append(p),
        clock=clock, scheduler=sched, max_fragments=3, crisis_predicate=lambda t: False,
    )
    for i in range(3):
        buf.push("k", f"f{i}")
    # The 4th push trips the fragment cap → the first batch flushes.
    buf.push("k", "f3")
    assert len(flushed) == 1
    assert flushed[0].reason == debounce.FlushReason.SIZE_CAP
    assert flushed[0].fragment_count == 3
