"""Session-end fan-out (Channels B + C) — idempotent, crash-safe.

On an explicit close (or a TUI exit with more than two user turns) Dr. Alex runs ONE
distillation and fans the result out to the durable memory system, exactly once per fact:

  - **Channel B — durable clinical learnings → ``memctl remember``** (one fact per memory,
    ``type:user``, ``tags:[therapy]``, ``sensitivity:high``, importance ≤80). On a RED
    session durable writes are withheld (conservative — the human/gardener reviews the
    inbox digest instead). Corrections are handled by ``supersede`` upstream, never by
    duplicate writes.
  - **Channel C — the full digest → ``~/agent-memory/inbox/``**, scrubbed by the store's
    EXISTING scrub path before a single byte lands, then consolidated by the already-running
    nightly gardener.
  - the continuity brief is regenerated (G8 ``generated_at`` stamp) and ``last_session_at`` /
    ``last_topic`` are updated for the next session's G5 re-orientation.

**Crash-safety.** Finalization is split into ``begin`` (distill once, write an unfinalized
marker holding the digest + a deterministic inbox filename + a per-step ledger) and
``complete`` (run only the steps the ledger hasn't recorded, updating it after each). If the
process dies mid-fan-out, the next session start sees the marker and calls ``complete``
again — every step is individually idempotent (deterministic filename, per-fact ledger),
so replay never duplicates a memory or writes a second inbox file.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from dr_alex import continuity as _continuity
from dr_alex import digest as _digest
from dr_alex import memstore
from dr_alex import statefile
from dr_alex.digest import SessionDigest
from dr_alex.statefile import SessionState, UnfinalizedMarker

MIN_USER_TURNS = 2  # fan-out triggers only when a real conversation happened (> 2 user turns)


@dataclass
class FanoutResult:
    session_id: str
    remembered: list[str]  # memory ids actually written this run (+ replays)
    inbox_path: str | None
    continuity_written: bool
    risk_tier_max: str
    durable_withheld: bool  # True on RED (conservative)
    scrub_failed: bool = False


def should_finalize(user_turns: int, *, explicit_close: bool) -> bool:
    """Explicit close always finalizes; an incidental exit needs > 2 user turns."""
    if explicit_close:
        return user_turns > 0
    return user_turns > MIN_USER_TURNS


# ---------------------------------------------------------------------------
# begin: distill once + write the crash-safety marker.
# ---------------------------------------------------------------------------


def begin(
    turns: list[tuple[str, str]],
    *,
    session_id: str,
    started_at: str,
    risk_tier_max: str,
    now: _dt.datetime,
    distill_fn=_digest.distill,
    state_path: Path | None = None,
) -> UnfinalizedMarker:
    """Distill the session and persist the unfinalized marker (the point of no half-work)."""
    digest = distill_fn(
        turns, session_id=session_id, started_at=started_at,
        risk_tier_max=risk_tier_max, now=now,
    )
    # Phase-4 seam: the user's own mood chips are ground truth — prefer them over the
    # model's inferred mood_in/mood_out when they were recorded this session.
    try:
        from dr_alex import statedb

        open_mood, close_mood = statedb.session_moods(session_id)
        if open_mood is not None:
            digest.mood_in = open_mood
        if close_mood is not None:
            digest.mood_out = close_mood
    except Exception:  # noqa: BLE001 — the mood seam is best-effort
        pass
    marker = UnfinalizedMarker(
        session_id=session_id,
        started_at=started_at,
        end_ts=digest.ended_at,
        inbox_filename=_digest.inbox_filename(session_id, now),
        digest=_digest.to_jsonable(digest),
        remembered=[],
        inbox_written=False,
        continuity_written=False,
    )
    statefile.set_unfinalized(marker, state_path)
    return marker


# ---------------------------------------------------------------------------
# complete: run only the not-yet-done steps; idempotent on replay.
# ---------------------------------------------------------------------------


def complete(
    marker: UnfinalizedMarker,
    *,
    now: _dt.datetime | None = None,
    remember_fn=memstore.remember,
    scrub_fn=memstore.scrub_document,
    inbox_dir_fn=memstore.inbox_dir,
    continuity_fn=_digest.regenerate_continuity,
    save_continuity_fn=_continuity.save_continuity_text,
    state_path: Path | None = None,
) -> FanoutResult:
    """Complete (or resume) the fan-out for one session. Every step is idempotent."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    digest: SessionDigest = _digest.from_jsonable(marker.digest)
    is_red = digest.risk_tier_max == "RED"

    written_ids = _channel_b_durable(marker, digest, is_red, remember_fn, state_path)
    inbox_path, scrub_failed = _channel_c_inbox(marker, digest, scrub_fn, inbox_dir_fn, state_path)
    _regenerate_continuity(marker, digest, now, continuity_fn, save_continuity_fn, state_path)
    _finalize_state(marker, digest, state_path)

    return FanoutResult(
        session_id=marker.session_id,
        remembered=written_ids,
        inbox_path=inbox_path,
        continuity_written=marker.continuity_written,
        risk_tier_max=digest.risk_tier_max,
        durable_withheld=is_red,
        scrub_failed=scrub_failed,
    )


def _channel_b_durable(marker, digest, is_red, remember_fn, state_path) -> list[str]:
    """Write durable learnings (skip on RED; skip already-ledgered indices). Idempotent."""
    written_ids: list[str] = []
    if is_red:
        return written_ids
    remembered_idx = list(marker.remembered)
    for i, learning in enumerate(digest.durable_learnings):
        if i in remembered_idx:
            continue
        res = remember_fn(learning, tags=["therapy"], sensitivity="high",
                          importance=memstore.IMPORTANCE_MAX, memtype="user")
        if res.ok:
            if res.id:
                written_ids.append(res.id)
            remembered_idx.append(i)
            marker.remembered = remembered_idx
            statefile.set_unfinalized(marker, state_path)
        # A failed write is left OUT of the ledger so a later replay retries it.
    return written_ids


def _channel_c_inbox(marker, digest, scrub_fn, inbox_dir_fn, state_path) -> tuple[str | None, bool]:
    """Scrub + write the inbox digest (deterministic filename ⇒ replay overwrites, never dupes)."""
    if marker.inbox_written:
        return str(Path(inbox_dir_fn()) / marker.inbox_filename), False
    document = _digest.render_inbox_markdown(digest)
    try:
        clean = scrub_fn(document)
    except memstore.ScrubError:
        # Privacy fails safe: never write the unscrubbed digest. Ledger stays False so a
        # future replay retries; report loudly upward.
        return None, True
    inbox = Path(inbox_dir_fn())
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / marker.inbox_filename
    path.write_bytes(clean)
    marker.inbox_written = True
    statefile.set_unfinalized(marker, state_path)
    return str(path), False


def _regenerate_continuity(marker, digest, now, continuity_fn, save_continuity_fn, state_path) -> None:
    """Regenerate the continuity brief once (G8 generated_at stamped by ``continuity_fn``)."""
    if marker.continuity_written:
        return
    prior = _continuity.load_continuity_text()
    save_continuity_fn(continuity_fn(digest, prior, now=now))
    marker.continuity_written = True
    statefile.set_unfinalized(marker, state_path)


def _finalize_state(marker, digest, state_path) -> None:
    """Persist last_session_at/last_topic + generated_at, then clear the marker."""
    st = statefile.load(state_path)
    # generated_at is the session's end whether the brief was (re)written this run or a prior
    # crashed one — so the G8 banner stays accurate across replay.
    st.continuity_generated_at = digest.ended_at
    st.last_session_at = digest.ended_at
    if digest.last_topic:
        st.last_topic = digest.last_topic
    st.unfinalized = None
    statefile.save(st, state_path)


def finalize_session(
    turns: list[tuple[str, str]],
    *,
    session_id: str,
    started_at: str,
    risk_tier_max: str,
    now: _dt.datetime | None = None,
    distill_fn=_digest.distill,
    state_path: Path | None = None,
    **complete_kwargs,
) -> FanoutResult:
    """The normal end-of-session path: begin (distill + marker) then complete."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    marker = begin(
        turns, session_id=session_id, started_at=started_at,
        risk_tier_max=risk_tier_max, now=now, distill_fn=distill_fn, state_path=state_path,
    )
    return complete(marker, now=now, state_path=state_path, **complete_kwargs)


def recover_if_needed(
    state: SessionState | None = None,
    *,
    now: _dt.datetime | None = None,
    state_path: Path | None = None,
    **complete_kwargs,
) -> FanoutResult | None:
    """At session start: if a prior fan-out didn't finish, complete it (idempotent)."""
    st = state or statefile.load(state_path)
    marker = st.marker()
    if marker is None:
        return None
    return complete(marker, now=now, state_path=state_path, **complete_kwargs)
