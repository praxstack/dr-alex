# Preserve an existing pending recovery session

Tracking issue: https://github.com/praxstack/dr-alex/issues/9

## Parent and problem

D06 reconciliation identified a narrow recovery bug in accepted Dr. Alex baseline `95a76894489062c51b9a5fa54f32614c5d116aa9`. `statefile.set_unfinalized(B)` currently replaces a valid pending session A. A failed TUI startup recovery can leave A pending while session B proceeds and later finalizes, losing A's retry marker.

## Scope

Guard the shared `set_unfinalized` mutation inside its existing locked `update` transaction. A different session must not replace a pending marker; the same session may persist retry/progress updates. Preserve current strict read/decrypt/serialization and legacy encryption migration. No stale branch transplant, caller/UI redesign, queue, cross-process lock, lease/fencing system, consent activation, new model call or sink.

## Frozen acceptance

1. With an existing valid encrypted marker A, `set_unfinalized(B)` raises a body-free RuntimeError and leaves the serialized state byte-for-byte unchanged, including unrelated fields. No session IDs, digest or key material appear in the error.
2. With A pending, synthetic `fanout.finalize_session(B)` fails before B reaches durable memory, inbox, continuity or canonical/Notion mirror sinks. A remains recoverable. Distillation stays at its existing point; tests inject it and all I/O seams.
3. A missing marker accepts A; an existing A accepts its own progress/retry update; recovering A still completes normally and can release the marker. A later B may then start.
4. Corrupt/unreadable state, malformed markers, missing/wrong keys and invalid serialization retain existing fail-closed behavior. Valid legacy migration remains allowed; it may encrypt legacy bytes while preserving the original pending session.
5. The conflict check and write share the existing in-process lock. An isolated two-thread setter race accepts only one session and does not clobber its marker. No new cross-process guarantee is claimed.
6. Focused state/fanout/privacy/atomic-write tests, full suite and required Ruff checks pass. A new regression must fail before the production edit. Review and signed commit are required; this assignment does not merge, push or deploy.

## Protected baseline and boundaries

Protected: persona, golden crisis corpus, triage/gates, identity policy, original memory-architecture evaluator and its 2,100-line cap, all user data, Keychain and live sinks. Do not amend or activate the preserved Ticket03 candidate. This repair does not accept the broader memory architecture, guarantee exactly-once crash recovery, or retain/queue B when A blocks it.

Mutable implementation paths: `dr_alex/statefile.py`, `tests/test_statefile.py`, `tests/test_fanout.py`; only if a direct regression requires it, `tests/test_recovery_privacy.py`. Scoped documentation: this ticket. No changes to `fanout.py`, app/PWA callers, shared test fixtures or dependencies without stopping to report the need.

Use the owned `fix/preserve-pending-recovery-20260907` worktree. Stop after two non-improving candidates and investigate; do not weaken acceptance. Rollback is the accepted baseline SHA above; preserve unrelated work and stage explicit paths only.
