# Review findings ledger

This ledger records document-review findings outside the governing content hash.

## Resolved in v2

### PARENT-001: finalize hook carries no transcript

- **Evidence:** Hermes `hermes_cli/lifecycle.py:40-63` and `cli.py:1304-1316` pass session metadata only.
- **Resolution:** H1 is removed from this implementation run. The later architecture keeps the hook body-free and requires an authorized committed-session reader.

### CROSS-001: retention did not control transcript persistence

- **Sources:** Codex C-B1; Grok G-B2.
- **Resolution:** v2 defines the shared `record_turn_telemetry` seam and makes durable memory depend on transcript retention.

### CROSS-002: global plaintext recovery marker

- **Sources:** Codex C-B2/C-B5; Grok G-M3.
- **Resolution:** v2 uses encrypted, unique per-session operation rows in existing `state.db` and deterministic step receipts.

### CROSS-003: identity and clinical isolation overclaim

- **Sources:** Codex C-B3/C-B4; Grok G-B3/G-B6.
- **Resolution:** v2 separates subject, request actor, and source. Current-run M1 is request-flag hardening only. Physical clinical isolation is a later human-gated service and key design.

### CROSS-004: unsafe sequence and current sink expansion

- **Sources:** Codex C-M5; Grok G-B1/G-M4.
- **Resolution:** D1 adds no new live PWA sink. Fan-out execution is synthetic and injected only. Every current sink is inventoried.

### CROSS-005: PWA session ownership

- **Sources:** Codex C-M1; Grok G-B3.
- **Resolution:** token resolution returns device ID, sessions bind to one device actor, and cross-device access externally returns not found.

### CROSS-006: consent evidence and withdrawal overclaim

- **Sources:** Codex C-M2/C-M3; Grok G-M1/G-M2.
- **Resolution:** receipts bind copy, purpose, retention policy, locale, channel, actor, and source. API grants are isolated-test-only. Withdrawal stops later work but v2 does not claim deletion product completion.

### CROSS-007: status, ordering, compatibility, and budget conflicts

- **Sources:** Codex C-M4/C-M6 and minor findings; Grok G-B4/G-B8/G-B9/G-B10.
- **Resolution:** one lifecycle enum and one identity rule; consent precedes recovery; TUI stays unchanged by default; six implementation tickets fit the eight-commit ceiling.

### CROSS-008: scope drift

- **Sources:** Codex CUT findings; Grok CUT findings.
- **Resolution:** graph, vector, per-turn retrieval, second event log, H1, physical isolation, activation, export product work, and claims of completed user controls are outside this run.

### CROSS-009: recall and full-body flag bypass share one root cause

- **Source:** parent trace of `recall.py:210-215`, `mcp.py:417-445`, `mcp.py:476-499`, and `tests/test_mcp.py:270-289`.
- **Resolution:** M1-A now applies the existing launch-agent gate to both `include_sensitive=true` recall and full-body fetch. The unsafe general-client recall assertion is explicitly superseded before implementation and replaced by the frozen v2 denial test.

### CROSS-010: rc2 ownership and recovery coupling

- **Source:** Grok rc2 falsification against live PWA routes, statefile, and agent-memory source.
- **Resolution:** rc3 makes owner binding always-on and separate from consent, defines start/turn/check-in/end creation rules, narrows global endpoint claims, encrypts the existing TUI marker, extracts marker-free `complete_digest`, adds atomic same-session create-or-load plus resume leases, qualifies legacy transcript behavior, defines policy-state writes outside the telemetry kill-switch, adds expiry and abuse tests, removes policy-file work, and specifies same-descriptor metadata-first full-body authorization.

### CROSS-011: frozen evidence source contains private clinical material

- **Source:** six-agent verification batch `deleg_9f2d0cc5`, privacy and identity-drift seat.
- **Status:** **RESOLVED BY HUMAN-APPROVED GOVERNANCE V3.** The restricted narrative reports remain preserved but non-governing and are excluded from review prompts, tickets, and Git-derived evidence.
- **Disposition:** `GOVERNING-EVIDENCE-v3.md`, `EVALUATOR-v3.md`, and v3 `RUN-CONTRACT.md` form the content-free governing baseline. Their hashes are frozen in `verification-receipt.md`.

### CROSS-012: ordinary PWA UI has no reachable end lifecycle

- **Source:** six-agent runtime verification against `room/app.js`, `room/index.html`, and `tests/test_alexd.py`.
- **Status:** verified current defect, parked from RC3 implementation because live PWA durable finalization remains disabled.
- **Disposition:** a later activation spec must add an accessible End Session action, server-side idle expiry, network-loss behavior, and browser-level tests. RC3 must not claim ordinary UI lifecycle parity.

### CROSS-013: canonical destination replay has an external crash window

- **Source:** six-agent minimalism review of `agent-memory` verbs and reconciler.
- **Status:** later-stage blocker, not part of RC3's no-live-sink slice.
- **Disposition:** before any live writer, prove deterministic destination identity across canonical mutation and idempotency receipt. Passing an idempotency key from Dr. Alex is insufficient while a crash can occur between those actions.

### CROSS-014: v3 RC3 exact-hash lifecycle contradictions

- **Sources:** exact-hash Codex and Grok reviews under the frozen content-free v3 baseline.
- **RC3 verdict:** **FAIL.** Findings covered stale consent before pending-fragment drain and replay, default-off operation contradiction, missing initial lease/fencing, response-loss retry after session removal, payload retention in denied/RED branches, PWA-only enforcement ambiguity, ended-session reopening, stale v2 gates, and commit/diff wording.
- **RC4 resolution candidate:** consent re-resolves before drain, claim, and every sink step; default configuration creates no operation; denied/RED/writer-disabled terminal rows are body-free; authorized creation commits payload plus generation-1 lease atomically; every step is generation-fenced; duplicate End can return/resume an existing operation without reopening; ended IDs cannot restart; TUI/CLI remain explicit legacy; the six safety assets are hash-pinned; eight additive regressions cover the defects.
- **Status:** **REJECTED.** Exact RC4 Codex and Grok reviews both returned FAIL. The change-spec claims the lease before current-consent resolution, while architecture requires consent-before-claim; per-step consent is also not one shared contract.
- **Stop:** RC3 and RC4 are two consecutive no-gain candidates. V3 forbids RC5. See `V3-STALL-REPORT.md`.

## Open

- Exact RC4 hashes require independent PASS with zero blocker and zero major finding; a material RC4 failure triggers the two-no-gain stop rule.
- `memctl doctor` remains exit 7 and physical clinical isolation remains unready.
- The PWA End Session UX, physical deletion/restore proof, and Hermes integration remain later human-gated stages.

## Checked and not defects

- The Room JavaScript currently sends no consent grant.
- Existing Dr. Alex transcripts use Fernet encryption at rest.
- Current TUI and one-shot behavior remain unchanged by default in v2.
