# Codex architecture and change-spec review

**Reviewer:** OpenAI Codex CLI 0.149.0, read-only sandbox  
**Verdict:** FAIL  
**Date:** 2026-08-23

## Blockers

### C-B1 Transcript retention does not control persistence

Current shared turn handling writes user and assistant bodies into `state.db`. D1 resolves consent only at session start and finalization, so a denied retention grant cannot suppress transcript rows while preserving body-free safety telemetry.

**Repair:** Add one consent-aware persistence seam in the shared turn pipeline.

### C-B2 Recovery marker persists derived content in plaintext

`UnfinalizedMarker.digest` is serialized to `data/session_state.json`. Mode `0600` is not the promised encrypted clinical boundary.

**Repair:** Encrypt marker payloads or persist only an opaque reference to encrypted per-session recovery state. Withdrawal and deletion must cover abandoned markers.

### C-B3 Principal identity is self-asserted

`memctl mcp --client NAME` plus a policy file lets any same-account process claim an approved name. It cannot prove that a general process lacks clinical access.

**Repair:** Define a non-self-asserted process boundary, such as a dedicated service identity plus Unix-socket permissions, or a separately reviewed credential.

### C-B4 Clinical encryption is not an implementation contract

M1 specifies Markdown roots and permissions but not the encryption mechanism, protected artifacts, key owner, rotation, restore, or fail-closed decryption behavior.

**Repair:** Pin the existing encryption design and its tests before M1 implementation.

### C-B5 Exactly-once claims exceed the existing marker

The current design has one global unfinished-session marker, can overwrite concurrent work, does not supply deterministic destination IDs, and does not persist completed lifecycle receipts for duplicate end requests.

**Repair:** Define per-session operation records, deterministic destination IDs, duplicate lookup, and overlapping-session tests.

### C-B6 Durable memory and transcript provenance conflict

The scopes allow durable memory while transcript retention is denied, but `MemoryFact` requires retained authorized event IDs.

**Repair:** Either require transcript retention for reusable memory or define an encrypted minimal provenance record that outlives bodies, with explicit withdrawal semantics.

## Major findings

1. **C-M1 PWA pairing discards device identity.** `require_device` validates but does not return the matched device principal; sessions are not bound to an owner. Return a verified device principal and reject cross-device session access.
2. **C-M2 Consent receipt lacks evidence.** Pin consent-copy version, locale, purpose, retention policy, and acquisition channel. Activation still requires reviewed copy and separate affirmative choices.
3. **C-M3 Withdrawal/deletion lacks callable contracts.** Define authenticated inspect, correct, forget, export, reset, status, deadline, and partial-result behavior.
4. **C-M4 Recovery ordering is wrong.** Resolve trusted identity and current consent before recovery and retrieval, then pass both into those operations.
5. **C-M5 D1 could write to the current insecure root before M1.** Require a default-disabled runtime gate and synthetic destination until M1 passes. Test that the default installation makes no new durable write.
6. **C-M6 Budget mismatch.** The frozen contract allows eight implementation commits; the spec lists nine implementation tickets before the human gate.

## Minor findings

1. Align status labels to `review active, implementation blocked`.
2. Reject unknown consent keys with HTTP 422 instead of ignoring them.
3. Require UTC offsets, deterministic tie-breaking, and fail-closed malformed-row handling for receipt timestamps.

## Cuts

1. Keep vector, temporal, adjacency, and graph implementation out of v1.
2. Move configuration keys to the first ticket that consumes them.
3. Do not make the review machinery part of the product gate beyond the independent privacy/security and conformance passes required by the frozen contract.

## Minimum repair set

1. Make transcript persistence consent-aware.
2. Replace the plaintext single-slot marker with encrypted per-session operations and durable receipts.
3. Define a real authenticated clinical process identity and encryption boundary.
4. Resolve memory-versus-provenance semantics.
5. Bind PWA sessions and consent to verified device principals.
6. Add enforceable withdrawal/deletion operations and keep rollout disabled.
7. Reconcile the eight-commit budget and document phase status.
