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
import hashlib
import inspect
import json
import logging
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("dr_alex.fanout")

from dr_alex import config, crypto, memstore, statedb, statefile
from dr_alex import continuity as _continuity
from dr_alex import digest as _digest
from dr_alex.digest import SessionDigest
from dr_alex.statefile import SessionState, UnfinalizedMarker

MIN_USER_TURNS = 2  # fan-out triggers only when a real conversation happened (> 2 user turns)
_SYNTHETIC_SEAM_KEYS = frozenset(
    {
        "distill_fn",
        "remember_fn",
        "scrub_fn",
        "inbox_dir_fn",
        "load_continuity_fn",
        "continuity_fn",
        "save_continuity_fn",
        "mirror_fn",
    }
)


@dataclass
class FanoutResult:
    session_id: str
    remembered: list[str]  # memory ids actually written this run (+ replays)
    inbox_path: str | None
    continuity_written: bool
    risk_tier_max: str
    durable_withheld: bool  # True on RED (conservative)
    scrub_failed: bool = False
    # Phase 6 — canonical record (local truth) + Notion mirror.
    active_file_path: str | None = None
    notion_op: str | None = None  # "create" | "patch" | None (disabled / failed)
    complete: bool = True


@dataclass(frozen=True)
class LifecycleReceipt:
    status: str
    operation_id: str
    memory_written: bool = False
    error_class: str | None = None


class _FinalizationLeaseLost(RuntimeError):
    pass


class _FinalizationConsentWithdrawn(RuntimeError):
    pass


_OPERATIONAL_FINALIZATION_ERRORS = (
    OSError,
    sqlite3.Error,
    crypto.CryptoError,
    json.JSONDecodeError,
    memstore.ScrubError,
)


def _receipt(operation: statedb.FinalizationOperation) -> LifecycleReceipt:
    try:
        steps = json.loads(operation.step_state)
        memory_written = bool(steps.get("memory_written", steps.get("remembered")))
    except (AttributeError, TypeError, ValueError):
        memory_written = False
    return LifecycleReceipt(
        operation.status,
        operation.operation_id,
        memory_written=memory_written,
        error_class=operation.error_class,
    )


def _pending_receipt(operation: statedb.FinalizationOperation) -> LifecycleReceipt:
    receipt = _receipt(operation)
    return LifecycleReceipt(
        "recovery_pending",
        receipt.operation_id,
        memory_written=receipt.memory_written,
        error_class=receipt.error_class,
    )


def _complete_synthetic_runner(seams: dict[str, object] | None) -> bool:
    return (
        isinstance(seams, dict)
        and set(seams) == _SYNTHETIC_SEAM_KEYS
        and all(callable(value) for value in seams.values())
    )


def _sink_id(subject_id: str, session_id: str, step: str, policy_version: str) -> str:
    components = json.dumps(
        [subject_id, session_id, step, policy_version],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return f"dr-alex-finalize-v1:{hashlib.sha256(components).hexdigest()}"


def _step_state(marker: UnfinalizedMarker, *, memory_written: bool | None = None) -> str:
    value = {
        "remembered": marker.remembered,
        "inbox_written": marker.inbox_written,
        "continuity_written": marker.continuity_written,
        "mirror_written": marker.mirror_written,
    }
    if memory_written is not None:
        value["memory_written"] = memory_written
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def finalize_authorized_session(
    session_id: str,
    subject_id: str,
    source: str,
    _consent: statedb.EffectiveConsent | None = None,
    *,
    risk_tier_max: str = "GREEN",
    turns: list[tuple[str, str]] | None = None,
    started_at: str = "",
    distill_fn=None,
    synthetic_seams: dict[str, object] | None = None,
    now: _dt.datetime | None = None,
) -> LifecycleReceipt:
    """Finalize one consent-authorized PWA session or replay its stored receipt."""
    operation = statedb.get_finalization_operation(session_id)
    if operation is not None and (operation.subject_id, operation.source) != (
        subject_id,
        source,
    ):
        raise ValueError("finalization owner mismatch")
    if operation is not None and operation.payload_enc is None:
        return _receipt(operation)
    consent = statedb.resolve_consent(subject_id, source)
    fixed_now = now

    def lease_now() -> _dt.datetime:
        return fixed_now or _dt.datetime.now(_dt.UTC)

    now = lease_now()
    worker_id = secrets.token_hex(16)
    lease_seconds = config.recovery_timeout_seconds()
    owns_lease = False
    if operation is None:
        payload = None
        lease_owner = None
        policy_version = config.memory_policy_version()
        if not consent.transcript_retention:
            status = "closed_transient"
        elif risk_tier_max == "RED":
            status = "finalized_red_withheld"
        elif not consent.durable_memory:
            status = "finalized_no_memory_consent"
        elif not config.pwa_durable_finalization_enabled():
            status = "finalization_disabled"
        else:
            payload = json.dumps(
                {
                    "history": turns or [],
                    "inbox_filename": f"{_sink_id(subject_id, session_id, 'inbox', policy_version)}.md",
                    "policy_version": policy_version,
                    "risk_tier_max": risk_tier_max,
                    "started_at": started_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            status = "running"
            lease_owner = worker_id
        operation = statedb.create_finalization(
            session_id,
            subject_id=subject_id,
            source=source,
            status=status,
            payload=payload,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds if lease_owner is not None else None,
            now=now,
        )
        owns_lease = (
            payload is not None
            and operation.lease_owner == worker_id
            and operation.lease_generation == 1
        )
        if payload is not None and not owns_lease:
            return _pending_receipt(operation)
    else:
        if not statedb.claim_finalization(
            operation.operation_id,
            lease_owner=worker_id,
            lease_seconds=lease_seconds,
            now=now,
        ):
            return _pending_receipt(operation)
        operation = statedb.get_finalization_operation(session_id)
        if operation is None:
            raise RuntimeError("claimed finalization disappeared")
        owns_lease = True
        if not consent.transcript_retention or not consent.durable_memory:
            updated = statedb.update_finalization_fenced(
                operation.operation_id,
                lease_owner=worker_id,
                lease_generation=operation.lease_generation,
                step_state=operation.step_state,
                status="finalized_no_memory_consent",
                clear_payload=True,
                release_lease=True,
                error_class="consent_withdrawn",
                now=lease_now(),
            )
            current = statedb.get_finalization_operation(session_id)
            if current is None:
                raise RuntimeError("finalization disappeared")
            return _receipt(current) if updated else _pending_receipt(current)
    if operation.payload_enc is None:
        return _receipt(operation)

    def current_receipt() -> LifecycleReceipt:
        current = statedb.get_finalization_operation(session_id)
        if current is None:
            raise RuntimeError("finalization disappeared")
        if current.payload_enc is None:
            return _receipt(current)
        return _pending_receipt(current)

    def require_current_consent(step_state: str) -> statedb.EffectiveConsent:
        current = statedb.resolve_consent(subject_id, source)
        if current.transcript_retention and current.durable_memory:
            return current
        if not statedb.update_finalization_fenced(
            operation.operation_id,
            lease_owner=worker_id,
            lease_generation=operation.lease_generation,
            step_state=step_state,
            status="finalized_no_memory_consent",
            clear_payload=True,
            release_lease=True,
            error_class="consent_withdrawn",
            now=lease_now(),
        ):
            raise _FinalizationLeaseLost
        raise _FinalizationConsentWithdrawn

    try:
        consent = require_current_consent(operation.step_state)
    except (_FinalizationLeaseLost, _FinalizationConsentWithdrawn):
        return current_receipt()

    def fence_failure(exc: Exception) -> LifecycleReceipt:
        current = statedb.get_finalization_operation(session_id)
        if current is None:
            raise RuntimeError("finalization disappeared") from exc
        error_class = type(exc).__name__
        _log.warning(
            "finalization_failed source=%s status=recovery_pending error_class=%s",
            source,
            error_class,
        )
        updated = statedb.update_finalization_fenced(
            operation.operation_id,
            lease_owner=worker_id,
            lease_generation=operation.lease_generation,
            step_state=current.step_state,
            status="recovery_pending",
            release_lease=True,
            error_class=error_class,
            now=lease_now(),
        )
        if not updated:
            return current_receipt()
        current = statedb.get_finalization_operation(session_id)
        if current is None:
            raise RuntimeError("finalization disappeared") from exc
        return _receipt(current)

    def run_owned() -> LifecycleReceipt:
        if not _complete_synthetic_runner(synthetic_seams):
            if owns_lease:
                updated = statedb.update_finalization_fenced(
                    operation.operation_id,
                    lease_owner=worker_id,
                    lease_generation=operation.lease_generation,
                    step_state=operation.step_state,
                    status="finalization_unavailable",
                    release_lease=True,
                    error_class="runner_unavailable",
                    now=lease_now(),
                )
                current = statedb.get_finalization_operation(session_id)
                if current is None:
                    raise RuntimeError("finalization disappeared")
                return _receipt(current) if updated else _pending_receipt(current)
            return _receipt(operation)
        assert synthetic_seams is not None
        runner = synthetic_seams.copy()
        runner_distill = runner.pop("distill_fn")
        assert callable(runner_distill)
        envelope = json.loads(crypto.decrypt(operation.payload_enc) or "{}")
        policy_version = envelope.get("policy_version")
        if not isinstance(policy_version, str):
            policy_version = config.memory_policy_version()
        digest_json = envelope.get("digest")
        if not isinstance(digest_json, dict):
            history = [
                (str(item[0]), str(item[1]))
                for item in envelope.get("history", [])
                if isinstance(item, (list, tuple)) and len(item) == 2
            ]
            digest = (distill_fn or runner_distill)(
                history,
                session_id=session_id,
                started_at=str(envelope.get("started_at", started_at)),
                risk_tier_max=str(envelope.get("risk_tier_max", risk_tier_max)),
                now=now,
            )
            if not isinstance(digest, SessionDigest):
                raise TypeError("synthetic distill returned invalid digest")
            digest_json = _digest.to_jsonable(digest)
            envelope = {
                "digest": digest_json,
                "inbox_filename": envelope.get("inbox_filename"),
                "policy_version": policy_version,
            }
            if not statedb.update_finalization_fenced(
                operation.operation_id,
                lease_owner=worker_id,
                lease_generation=operation.lease_generation,
                step_state=operation.step_state,
                payload=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
                now=lease_now(),
            ):
                current = statedb.get_finalization_operation(session_id)
                if current is None:
                    raise RuntimeError("finalization disappeared")
                return _pending_receipt(current)
        steps = json.loads(operation.step_state)
        marker = UnfinalizedMarker(
            session_id=session_id,
            started_at=digest_json["started_at"],
            end_ts=digest_json["ended_at"],
            inbox_filename=envelope.get("inbox_filename")
            or _digest.inbox_filename(session_id, now),
            digest=digest_json,
            remembered=steps.get("remembered", []),
            inbox_written=steps.get("inbox_written", False),
            continuity_written=steps.get("continuity_written", False),
        )

        def persist_step(value):
            if not statedb.update_finalization_fenced(
                operation.operation_id,
                lease_owner=worker_id,
                lease_generation=operation.lease_generation,
                step_state=_step_state(value),
                now=lease_now(),
            ):
                raise _FinalizationLeaseLost

        def before_step(_step: str) -> None:
            require_current_consent(_step_state(marker))
            if not statedb.renew_finalization(
                operation.operation_id,
                lease_owner=worker_id,
                lease_generation=operation.lease_generation,
                lease_seconds=lease_seconds,
                now=lease_now(),
            ):
                raise _FinalizationLeaseLost

        result = complete_digest(
            marker,
            persist_step=persist_step,
            before_step=before_step,
            idempotency_key_fn=lambda step: _sink_id(subject_id, session_id, step, policy_version),
            mirror_ledger=True,
            strict_sink_errors=True,
            now=now,
            **runner,
        )
        memory_written = bool(marker.remembered)
        updated = statedb.update_finalization_fenced(
            operation.operation_id,
            lease_owner=worker_id,
            lease_generation=operation.lease_generation,
            step_state=_step_state(marker, memory_written=memory_written),
            status="finalized" if result.complete else "recovery_pending",
            clear_payload=result.complete,
            release_lease=True,
            error_class=None if result.complete else "fanout_incomplete",
            now=lease_now(),
        )
        current = statedb.get_finalization_operation(session_id)
        if current is None:
            raise RuntimeError("finalization disappeared")
        return _receipt(current) if updated else _pending_receipt(current)

    try:
        return run_owned()
    except (_FinalizationLeaseLost, _FinalizationConsentWithdrawn):
        return current_receipt()
    except _OPERATIONAL_FINALIZATION_ERRORS as exc:
        return fence_failure(exc)
    except Exception as exc:
        fence_failure(exc)
        raise


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
        turns,
        session_id=session_id,
        started_at=started_at,
        risk_tier_max=risk_tier_max,
        now=now,
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
    except Exception as exc:  # noqa: BLE001 — the mood seam is best-effort
        _log.warning("mood seam unavailable for digest: %s", type(exc).__name__)
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
    state_path: Path | None = None,
    **seams,
) -> FanoutResult:
    """Complete legacy TUI fan-out through the shared digest writer."""
    return complete_digest(
        marker,
        persist_step=lambda value: statefile.set_unfinalized(value, state_path),
        before_mirror=lambda complete: _finalize_state(
            marker,
            _digest.from_jsonable(marker.digest),
            state_path,
            keep_marker=not complete,
        ),
        **seams,
    )


def complete_digest(
    marker: UnfinalizedMarker,
    *,
    persist_step,
    now: _dt.datetime | None = None,
    remember_fn=memstore.remember,
    scrub_fn=memstore.scrub_document,
    inbox_dir_fn=memstore.inbox_dir,
    load_continuity_fn=_continuity.load_continuity_text,
    continuity_fn=_digest.regenerate_continuity,
    save_continuity_fn=_continuity.save_continuity_text,
    mirror_fn=None,
    before_mirror=None,
    before_step=None,
    idempotency_key_fn=None,
    mirror_ledger: bool = False,
    strict_sink_errors: bool = False,
) -> FanoutResult:
    """Write one digest through injected seams without touching a recovery marker."""
    now = now or _dt.datetime.now(_dt.UTC)
    digest: SessionDigest = _digest.from_jsonable(marker.digest)
    is_red = digest.risk_tier_max == "RED"
    written_ids = _channel_b_durable(
        marker,
        digest,
        is_red,
        remember_fn,
        persist_step,
        idempotency_key_fn,
        before_step,
        strict_sink_errors,
    )
    inbox_path, scrub_failed = _channel_c_inbox(
        marker, digest, scrub_fn, inbox_dir_fn, persist_step, before_step
    )
    _regenerate_continuity(
        marker,
        digest,
        now,
        load_continuity_fn,
        continuity_fn,
        save_continuity_fn,
        persist_step,
        before_step,
    )
    incomplete = _fanout_incomplete(marker, digest, is_red)
    if incomplete:
        _log.warning(
            "session-end fan-out INCOMPLETE for %s: %s",
            marker.session_id,
            "; ".join(incomplete),
        )
    complete = not incomplete
    if before_mirror is not None:
        before_mirror(complete)
    active_path = notion_op = None
    if mirror_ledger:
        if not marker.mirror_written:
            if before_step is not None:
                before_step("mirror")
            key = idempotency_key_fn("mirror") if idempotency_key_fn is not None else None
            active_path, notion_op = _mirror_canonical(
                digest,
                mirror_fn=mirror_fn,
                idempotency_key=key,
                strict=True,
            )
            marker.mirror_written = True
            persist_step(marker)
        complete = complete and marker.mirror_written
    else:
        if before_step is not None:
            before_step("mirror")
        active_path, notion_op = _mirror_canonical(digest, mirror_fn=mirror_fn)
    return FanoutResult(
        session_id=marker.session_id,
        remembered=written_ids,
        inbox_path=inbox_path,
        continuity_written=marker.continuity_written,
        risk_tier_max=digest.risk_tier_max,
        durable_withheld=is_red,
        scrub_failed=scrub_failed,
        active_file_path=active_path,
        notion_op=notion_op,
        complete=complete,
    )


def _fanout_incomplete(marker, digest, is_red) -> list[str]:
    """Return human-readable reasons the fan-out is NOT fully done, or [] when complete (D5).

    On RED the durable Channel B is withheld by design (conservative), so it does not count
    as incomplete. Channel C (inbox) is incomplete whenever ``inbox_written`` is still False —
    the scrub-failed path leaves it False precisely so this keeps the marker for replay.
    """
    reasons: list[str] = []
    if not is_red and len(marker.remembered) < len(digest.durable_learnings):
        reasons.append(
            f"durable learnings {len(marker.remembered)}/{len(digest.durable_learnings)} written"
        )
    if not marker.inbox_written:
        reasons.append("inbox digest not written (scrub failed or pending)")
    if not marker.continuity_written:
        reasons.append("continuity brief not regenerated")
    return reasons


def _channel_b_durable(
    marker,
    digest,
    is_red,
    remember_fn,
    persist_step,
    idempotency_key_fn,
    before_step,
    strict_sink_errors,
) -> list[str]:
    """Write durable learnings (skip on RED; skip already-ledgered indices). Idempotent."""
    written_ids: list[str] = []
    if is_red:
        return written_ids
    remembered_idx = list(marker.remembered)
    for i, learning in enumerate(digest.durable_learnings):
        if i in remembered_idx:
            continue
        if before_step is not None:
            before_step(f"memory:{i}")
        # D5: a transient remember failure — whether it returns ok=False OR raises — must
        # leave this index OUT of the ledger so a later replay retries it, never silently
        # drop the learning. The marker is kept (see _fanout_incomplete) so recovery runs.
        try:
            kwargs = {
                "tags": ["therapy"],
                "sensitivity": "high",
                "importance": memstore.IMPORTANCE_MAX,
                "memtype": "user",
            }
            if idempotency_key_fn is not None:
                kwargs["idempotency_key"] = idempotency_key_fn(f"memory:{i}")
            res = remember_fn(learning, **kwargs)
        except Exception:  # noqa: BLE001 — PWA classifies errors at the operation boundary
            if strict_sink_errors:
                raise
            _log.warning(
                "durable remember failed (transient) for %s idx=%s — will retry on replay",
                marker.session_id,
                i,
            )
            continue
        if res.ok:
            if res.id:
                written_ids.append(res.id)
            remembered_idx.append(i)
            marker.remembered = remembered_idx
            persist_step(marker)
        # A failed write is left OUT of the ledger so a later replay retries it.
    return written_ids


def _channel_c_inbox(
    marker, digest, scrub_fn, inbox_dir_fn, persist_step, before_step
) -> tuple[str | None, bool]:
    """Scrub + write the inbox digest (deterministic filename ⇒ replay overwrites, never dupes)."""
    if marker.inbox_written:
        return str(Path(inbox_dir_fn()) / marker.inbox_filename), False
    if before_step is not None:
        before_step("inbox")
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
    persist_step(marker)
    return str(path), False


def _regenerate_continuity(
    marker,
    digest,
    now,
    load_continuity_fn,
    continuity_fn,
    save_continuity_fn,
    persist_step,
    before_step,
) -> None:
    """Regenerate the continuity brief once (G8 generated_at stamped by ``continuity_fn``)."""
    if marker.continuity_written:
        return
    if before_step is not None:
        before_step("continuity")
    prior = load_continuity_fn()
    save_continuity_fn(continuity_fn(digest, prior, now=now))
    marker.continuity_written = True
    persist_step(marker)


def _default_mirror(digest: SessionDigest) -> tuple[str | None, str | None]:
    """Write the canonical Active File (local truth), then mirror to Notion (graceful-disabled).

    Local FIRST: the human-readable record never depends on a network round-trip (council D4).
    The Notion mirror is idempotent and disabled until Prax provisions a Keychain token.
    """
    from dr_alex import notion, records

    active_path: str | None = None
    notion_op: str | None = None
    try:
        p = records.update_from_digest(digest)
        active_path = str(p)
    except Exception:  # noqa: BLE001 — the canonical record must never break session end
        active_path = None
    try:
        res = notion.mirror_session(digest, tier=digest.risk_tier_max)
        notion_op = res.op if res.ok else None
    except Exception:  # noqa: BLE001 — the mirror must never break session end
        notion_op = None
    return active_path, notion_op


def _mirror_canonical(
    digest: SessionDigest,
    *,
    mirror_fn=None,
    idempotency_key: str | None = None,
    strict: bool = False,
) -> tuple[str | None, str | None]:
    fn = mirror_fn or _default_mirror
    if strict and mirror_fn is not None:
        parameters = inspect.signature(fn).parameters.values()
        accepts_key = any(
            parameter.name == "idempotency_key" or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if accepts_key:
            return mirror_fn(digest, idempotency_key=idempotency_key)
        return mirror_fn(digest)
    try:
        return fn(digest)
    except Exception:  # noqa: BLE001 — belt-and-suspenders; never propagate from the mirror step
        return None, None


def _finalize_state(marker, digest, state_path, *, keep_marker: bool = False) -> None:
    """Persist last_session_at/last_topic + generated_at; clear the marker only if done.

    ``keep_marker`` (D5): when a durable step is still incomplete, DON'T clear ``unfinalized``
    — leave it so the next session-start recovery replays the missing steps. The G8 stamps are
    only advanced on a fully-finalized session, so the staleness banner never claims a brief
    is fresh while its regeneration is still pending.
    """
    if keep_marker:
        # Preserve the crash-safety marker persisted by the per-step ledger; a later replay
        # completes the fan-out and finalizes for real. Do not advance the G8 stamps yet.
        # Checked before touching the state file at all — this path reads nothing and writes
        # nothing, so it cannot race the recovery worker.
        return

    def _apply(st) -> None:
        # generated_at is the session's end whether the brief was (re)written this run or a
        # prior crashed one — so the G8 banner stays accurate across replay.
        st.continuity_generated_at = digest.ended_at
        st.last_session_at = digest.ended_at
        if digest.last_topic:
            st.last_topic = digest.last_topic
        st.unfinalized = None

    # statefile.update holds the lock across load→mutate→save. Doing this as a bare
    # load/mutate/save would drop the marker written by a concurrent recovery worker.
    statefile.update(_apply, state_path)


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
    now = now or _dt.datetime.now(_dt.UTC)
    marker = begin(
        turns,
        session_id=session_id,
        started_at=started_at,
        risk_tier_max=risk_tier_max,
        now=now,
        distill_fn=distill_fn,
        state_path=state_path,
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
