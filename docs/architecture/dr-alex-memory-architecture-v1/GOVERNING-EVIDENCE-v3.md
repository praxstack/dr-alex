# Dr. Alex Memory Architecture v3 Governing Evidence

**Status:** Human-approved content-free baseline  
**Approved:** 2026-08-23  
**Supersedes as governing input:** the two restricted narrative reports  
**Privacy rule:** no conversation bodies, clinical excerpts, inferred biography, or identifying case details

## 1. Evidence precedence

1. This human-approved content-free baseline.
2. Pinned current source and executable synthetic tests.
3. Current-state addenda when they conflict with older narrative prose.
4. The original restricted reports as historical clinical references only.

Source observations may refine current-state claims. They may not weaken these safety requirements.

## 2. Pinned source baselines

| System | Commit | Governing use |
|---|---|---|
| Dr. Alex | `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d` | runtime, safety, lifecycle, and tests |
| agent-memory | `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38` | canonical store, retrieval, authorization, and tests |
| Hermes | `d5281f59819d2ea2ce6754faec2ce317c92366c8` | profile/session lifecycle reference only; no edits authorized |
| therapy-stack | `9ce6054195366eb57b414ecd51b087487cdd22c5` | historical reference only |

## 3. Verified current state

1. TUI, one-shot CLI, and alexd share the same safety-first turn engine.
2. The TUI conditionally invokes the existing durable finalizer and recovery path.
3. PWA `/session/end` closes telemetry and in-memory state but does not invoke equivalent durable fan-out.
4. The ordinary PWA UI has no proven reachable End Session flow.
5. One-shot CLI has no reusable-memory finalization contract.
6. Hermes persists profile-local sessions, but Telegram and desktop remain separate session threads.
7. Manual agent-memory MCP availability does not prove automatic lifecycle capture.
8. Hermes' finalization hook is body-free and cannot supply transcript content by itself.
9. agent-memory uses Markdown as canonical authority and rebuildable derived indexes.
10. Request `include_sensitive=true` can currently expose high-sensitivity recall snippets and full bodies without the intended launch-identity authorization.
11. Default and therapist Hermes profiles currently point to the same physical agent-memory root.
12. Process-local client naming is not a clinical-grade identity boundary.
13. Live semantic retrieval is inactive; lexical recall remains available.
14. `memctl doctor` exits 7 because of carried operational defects. The store can still serve, but it does not satisfy its full acceptance contract.
15. Existing destination idempotency has a crash window between canonical mutation and receipt/ledger persistence.

## 4. Human-approved safety requirements

1. Current-turn deterministic triage runs before retrieval, persistence, distillation, or network-dependent work.
2. Every supported surface executes the same RED classifier and local short-circuit. Human escalation is additive.
3. Message receipt authorizes transient processing only.
4. Transcript retention, durable memory, cross-context recall, and export require explicit scope-specific consent.
5. Non-consented sessions produce no durable body, summary, reusable fact, inbox note, continuity artifact, or external mirror under the enforced profile.
6. PWA sessions bind to authenticated paired-device actors independently of consent.
7. High-sensitivity recall and full-body reads require authenticated runtime authority. Request fields never grant authority.
8. Clinical storage requires a separately encrypted physical boundary and an identity stronger than a process-local client name before activation.
9. Canonical records remain separate from summaries, indexes, embeddings, and graph projections. Derived layers remain rebuildable.
10. User erasure overrides archive-by-default. Clinical data must not remain recoverable from Git history, indexes, WAL, caches, backups, or restore manifests before activation.
11. Real clinical migration and live activation require separate human-approved operations with rollback and non-resurrection evidence.
12. The encrypted standalone PWA remains available until replacement confidentiality, lifecycle, consent, deletion, backup/restore, and response-parity gates pass.
13. Tests, fixtures, logs, tickets, and review packets use synthetic content only.

## 5. Authorized increment

This run may implement only:

- always-on PWA session ownership;
- default-off consent receipts and transcript policy;
- encrypted legacy marker migration;
- per-session encrypted synthetic finalization operations with no live sink;
- a marker-free shared completion seam;
- denial of request-flag authority for high-sensitivity recall and full-body access;
- focused synthetic tests, local documentation, and local commits.

## 6. Prohibited increment

This run may not:

- create or activate a clinical root, key, OS identity, daemon, socket, or live policy;
- add Hermes transcript integration;
- migrate, copy, decrypt, delete, or purge real clinical data;
- change Telegram, gateway, cron, credentials, backups, therapist profile, or live services;
- claim universal continuity, physical clinical isolation, deletion completion, or product activation;
- send the restricted source reports or their private contents to external reviewers.

## 7. Later human gates

The following require new governing contracts:

- PWA End Session UX and idle expiry;
- clinical OS identity and encrypted-root provisioning;
- canonical destination replay repair for a live writer;
- user inspect, correct, forget, export, and reset controls;
- physical deletion and restore non-resurrection;
- Hermes integration and cross-surface identity;
- real-data migration and activation.
