# Spec: D1 Ticket 03 — Encrypted Synthetic Finalization Operations (v5.1)

**Status:** Approved by Prax 2026-08-25 (budget amendment: cap raised to 2,100 net implementation+test lines for the Dr. Alex repository, measured from baseline `e0dad8a3`)
**Normative sources:** `CHANGE-SPEC.md` sections 5.9, 6, 7, 10, 15-17; `EVALUATOR-v3.md` D1-F01..F17; RC4-R01..R08 candidate regressions
**Activation:** Prohibited. No merge, no push, no live sink binding.

## Problem Statement

A PWA session ends with consent granted and a durable-memory grant on record, but nothing durable happens: there is no encrypted, replay-safe finalization path for PWA sessions. The TUI has one (fan-out + crash-safety marker); the PWA does not. D1 is incomplete without it.

## Solution

One policy wrapper (`finalize_authorized_session`) over the existing fanout seam, plus a shared marker-free `complete_digest` extracted from existing fanout completion, plus a `finalization_operations` table in state.db using Fernet-encrypted payloads, fenced leases, and synthetic-only sinks. Production writer stays disabled by default; tests bind synthetic runners only.

## User Stories

1. As a PWA user ending a session without retention consent, I want the session recorded body-free as `closed_transient`, so that nothing of mine persists.
2. As a PWA user with retention but no durable grant, I want a body-free `finalized_no_memory_consent` receipt, so that my choice is respected.
3. As a PWA user whose session was RED, I want durable writes withheld (`finalized_red_withheld`), so that sensitive content never reaches memory.
4. As an operator running default config, I want `finalization_disabled` receipts, so that no sink ever runs without explicit enablement.
5. As an operator who enabled the flag but bound no runner, I want `finalization_unavailable` (HTTP 503), so that failure is loud, not silent.
6. As a PWA user with full grants and a synthetic runner, I want the digest finalized exactly once through synthetic sinks, so that recovery after a crash never duplicates a memory or file.
7. As a user whose consent was withdrawn mid-recovery, I want unfinished steps stopped and payloads erased under fence, so that withdrawal wins immediately.
8. As an operator replaying after partial failure, I want the operation to stay `recovery_pending`, so that unfinished work is visible.
9. As a caller losing a response, I want a duplicate End to return the same receipt or resume the same operation, so that retries are safe.
10. As an operator watching two overlapping sessions end, I want separate rows and payloads, so that no cross-session overwrite occurs.
11. As an auditor scanning persisted files, I want zero synthetic body or digest plaintext anywhere, so that privacy holds at rest.
12. As an operator changing policy versions, I want completed sessions left alone, so that history is not re-extracted.
13. As a caller hitting End while another caller runs, I want HTTP 202 pending semantics, so that concurrency degrades gracefully.
14. As a worker whose lease expired, I want takeover to increment generation and stale workers to write nothing, so that fencing holds.
15. As a TUI user, I want legacy behavior byte-identical apart from encrypted marker storage, so that nothing regresses.

## Implementation Decisions

- **Reuse, not parallel:** `complete_digest(digest_input, seams, persist_step)` is extracted from the existing fanout completion body. Legacy `fanout.complete` wraps it with its encrypted marker. There is ONE sink-writing implementation.
- **Wrapper:** `finalize_authorized_session(session_id, subject_id, source, history, risk_tier_max, consent, runner=None, seams=synthetic_only, now)` returning a body-free `LifecycleReceipt`. Implements CHANGE-SPEC section 10.3 algorithm verbatim: terminal branches first (no-retention → `closed_transient`; RED → `finalized_red_withheld`; no-durable → `finalized_no_memory_consent`; disabled → `finalization_disabled`), then create-or-load with `INSERT ... ON CONFLICT(session_id) DO NOTHING`, then claim via compare-and-swap, then runner execution with per-step consent re-resolution and lease renewal.
- **Schema:** new `finalization_operations` table exactly per section 5.9 columns; schema version bumped once; migration transactional, idempotent, telemetry-off independent; policy-state connection only.
- **Crypto:** payload Fernet-encrypted via existing `dr_alex.crypto`; terminal rows have `payload_enc`, `lease_owner`, `lease_expires_at` NULL (RC4-R03).
- **Config:** `DR_ALEX_PWA_DURABLE_FINALIZATION` (bool, false), `DR_ALEX_RECOVERY_TIMEOUT_SECONDS` (int 1..30, default 5). Unknown values fail closed.
- **Fencing:** every step/renewal/error/completion update repeats owner+generation predicate; zero updated rows = stale = stop before touching any sink. Lease max 30 seconds.
- **Determinism:** synthetic sink IDs derive from `subject_id + session_id + step + policy_version`.
- **step_state:** body-free JSON map (deterministic IDs + booleans only).

## Testing Decisions

- Test external behavior through the wrapper and HTTP surface, not internals. Prior art: `tests/test_identity_consent.py` fixtures (`_paired_device`, `_consent`, `_record`, TestClient helpers) and `tests/test_fanout.py` synthetic distillation seams.
- Every evaluator row D1-F01..F17 gets a named test. RC4-R01..R08 as additive candidate tests. Terminal-row NULL assertions per RC4-R03.
- RED-first per slice: write the failing test, prove red, implement minimal green.
- Full suite gate before any commit: `uv run pytest -q` exit 0; protected safety hashes unchanged; TUI/one-shot behavioral diff empty.

## Out of Scope

- Live sink binding or production runner registration.
- Merging, pushing, activation, Telegram, clinical-data migration.
- agent-memory changes (M1-A already committed).
- Editing frozen governing documents (v5 packet stays immutable; this spec extends via v5.1 amendment only).

## Further Notes

- Line budget: amended cap 2,100 net lines total for Dr. Alex from baseline; ticket 03 estimated 430-520 lines including tests; current usage 1,483.
- Budget checkpoint after each slice: if projected spend exceeds remaining headroom, stop and report rather than compress security code.
- Commit discipline: only reviewed slices commit; review loop (standards/spec/security) must return PASS with zero blockers/majors first.
