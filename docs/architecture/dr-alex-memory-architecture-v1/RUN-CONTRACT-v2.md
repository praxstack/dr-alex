# Dr. Alex Memory Architecture v2 Run Contract

**Frozen at:** 2026-08-23T14:15:00Z  
**Run class:** LARGE, multi-repository, identity-preserving  
**Status:** Review repair active; implementation blocked until v2 receives independent PASS  
**Supersedes:** `RUN-CONTRACT-v1.md`  
**Authorization:** The user explicitly requested iterative document review, defect repair, implementation, re-review, and commit. v1 remains the rollback artifact.

## 1. Product objective

Build the minimum existing-platform architecture that gives every authorized Dr. Alex conversation one auditable lifecycle across supported surfaces while preserving safety, privacy, provenance, correction, deletion, and explicit retention consent.

The full product program is complete only when later human-gated stages prove all of these outcomes:

1. A supported retained conversation reaches one idempotent processing lifecycle.
2. Raw transcripts, derived memory, and prompt context remain distinct layers.
3. Clinical memory is physically isolated, encrypted, authenticated, and unavailable to non-therapy clients outside the approved API.
4. Current-turn crisis triage remains independent of memory and preserves every existing Dr. Alex safety invariant.
5. Recall excludes stale, unauthorized, deleted, invalid, and context-inapplicable memories.
6. User-facing inspect, correct, forget, export, and reset operations have enforceable contracts.
7. The canonical write path and BM25 fallback require no graph, embedding, model, network service, or new memory product.

This implementation run cannot honestly complete outcomes 3, 5, or 6 without crossing later security and activation gates. It must not claim product completion. Its accepted product increment is:

- explicit, auditable local consent state;
- paired-device ownership for PWA sessions;
- consent-aware transcript persistence under the default-off enforced profile;
- encrypted legacy TUI marker digest plus encrypted per-session PWA operation records;
- one marker-free sink runner shared by legacy and synthetic paths;
- default-off PWA durable finalization with no new live sink;
- removal of request flags as authority for high-sensitivity recall snippets or full-body reads;
- specifications and tickets for the remaining human-gated stages.

## 2. Governing baseline

Human-approved evidence inputs remain immutable:

- `therapist-stack-audit-2026-08-22.html`
  - SHA-256: `d349628361212722c06901b365dfc81d135fb4279e9655f9b5947d2a4c6e9005`
- `dr-alex-memory-architecture-review-2026-08-23.html`
  - SHA-256: `1cc6e53eab0d1a7509f13d3aaf06db7c384d5d27fc382d3b47cf82a81372320c`
- `/Users/prax/Documents/Hermes-Reports/research-dr-alex-memory-architecture-20260823/waves/wave-03/adversarial-reverification.md`
  - verdict: `PASS`

Repository baselines:

- `dr-alex`: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`
- `agent-memory`: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`
- `therapy-stack`: `9ce6054195366eb57b414ecd51b087487cdd22c5`, reference only

Document-review evidence:

- `reviews/codex-review.md`: `FAIL`
- `reviews/grok-review.md`: `FAIL`
- `REVIEW-FINDINGS.md`: parent blocker ledger

The v2 architecture and change spec may change during document repair. Code implementation may start only after those documents receive a fresh independent PASS. Once code starts, this contract, the v2 specs, evaluator, thresholds, and holdouts freeze.

## 3. Protected controls and paths

The following cannot change in this run:

- the two governing reports, research evaluator, thresholds, or evidence policy;
- `/Users/prax/Developer/agent-stack/policies/identity-preservation.md`;
- private conversation content, clinical archives, therapist `state.db`, clinical source records, and backup archives;
- therapist profile `SOUL.md`, `USER.md`, `MEMORY.md`, `.env`, `config.yaml`, gateway state, Telegram routing, and cron activation;
- Dr. Alex triage-first, RED short-circuit, single LLM entry point, golden RED-recall, frozen-section integrity, deterministic output gates, encryption-at-rest, and loopback-only controls;
- agent-memory canonical authority, single-writer flock, supersede, quarantine, archive-by-default, fail-loud index state, and BM25 without optional services;
- unrelated dirty files in `/Users/prax/agent-memory` and `/Users/prax/therapy-stack`.

A protected control change requires another human-approved governing version. Tests may extend coverage but cannot weaken controls or rewrite expected outcomes to make a candidate pass.

## 4. Permitted mutable paths

Only isolated feature worktrees may change.

### Dr. Alex worktree

`/Users/prax/Development/Hermes-Projects/dr-alex-memory-architecture-v1`

Allowed:

- v2 architecture, change-spec, review, ticket, and receipt documents;
- local consent and paired-device session ownership;
- transcript persistence policy at the existing shared turn seam;
- encryption migration for the legacy TUI marker digest;
- encrypted per-session finalization operations in the existing `state.db`;
- marker-free fan-out completion extraction shared by legacy and synthetic paths;
- a default-off PWA lifecycle wrapper using existing fan-out seams and synthetic sinks;
- focused synthetic tests and body-free telemetry.

Prohibited:

- changes to safety triage or crisis content;
- new live PWA durable writes;
- new Notion, Active File, inbox, continuity, canonical memory, or backup output;
- live state, clinical records, corpus, secrets, or activation.

### agent-memory worktree

A separate clean worktree from `a01bc4c`.

Allowed in this run:

- OpenSpec and threat-model artifacts;
- removal of `include_sensitive` as an authorization mechanism for recall and full-body fetch;
- focused synthetic authorization tests.

Not allowed until a later approved contract:

- creation of a clinical root, key, service identity, user account, socket, daemon, or live policy;
- claims of physical clinical isolation;
- moving, decrypting, importing, or deleting memory.

### Hermes

No Hermes source or profile edit is allowed in this run. H1 remains a later stage. Its contract must use the body-free finalize hook plus an authorized committed-session reader. It must not add transcript bodies to lifecycle hook payloads.

## 5. Frozen evaluator and holdout

Acceptance evidence is fixed before code implementation:

- full baseline suites in Dr. Alex and agent-memory;
- the legacy agent-memory assertion that `client=codex` plus `include_sensitive=true` returns high-sensitivity recall is explicitly superseded by v2 before implementation; the replacement test requires launch-agent authorization and is part of the frozen v2 evaluator;
- Dr. Alex crisis corpus and immutable safety tests;
- agent-memory keyword and natural-language golden sets, with baseline defects carried honestly;
- synthetic Memory Torture Deck and crisis trajectories described by the verified research workspace;
- new v2 tests named before implementation;
- no private clinical text in fixtures, logs, reports, or review prompts.

Candidate acceptance requires comparison with the original repository baseline and the current accepted candidate, strict improvement on target behavior, and no protected regression.

## 6. Budgets and stop rule

- Maximum implementation commits: `8` across repositories.
- Maximum independent review/fix rounds per implementation slice: `5`.
- Maximum candidate diff: `1500` net changed lines per repository before a new scope review.
- Maximum parallel external reviewers per gate: `6`.
- Stop at the first hard budget limit or after `2` consecutive candidates produce no held-out improvement.
- Do not weaken a gate, change a holdout, broaden done, or extend the budget to hide a stall.

Document-only review commits do not count as implementation commits.

## 7. Commit and activation boundary

This run authorizes local feature branches and verified commits. It does not authorize:

- merge to `main`;
- push or public pull requests containing sensitive architecture details;
- therapist gateway restart or configuration;
- a live Hermes hook or plugin;
- clinical data migration, copy, decryption, deletion, or purge;
- Telegram, backup, credential, retention, OS-user, service, socket, key, or clinical policy changes.

Those operations retain the standing human gate.

## 8. Rollback pointers

- Dr. Alex code rollback: `git reset --hard e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d` in the isolated worktree.
- Agent-memory code rollback: `git reset --hard a01bc4cb9697aaeff69671d82ea2dbca1f32cd38` in its isolated worktree.
- Run-contract rollback: `RUN-CONTRACT-v1.md`.
- Never run rollback commands in the original dirty worktrees.

## 9. First tracer bullet

The first implementation slice is test-first. It makes one intentional live security change: PWA session ownership becomes device-bound. Consent enforcement, transcript policy, TUI sink behavior, and PWA durable finalization remain unchanged by default.

> Resolve one stable local subject and a verified paired-device actor, persist explicit default-deny consent receipts in existing `state.db`, always bind PWA session start/turn/check-in/end to the verified device, and suppress transcript rows when retention consent is denied in an isolated consent-enforcement profile.

Rules:

- An authenticated local turn implies transient processing. D1 does not persist a separate transient grant.
- PWA ownership is independent of consent and always enforced after D1. Only start and check-in without a caller session ID create sessions.
- Durable memory requires active transcript-retention consent only under the enforced profile.
- The Room JavaScript sends no grant before reviewed consent copy and human activation approval.
- Existing TUI sink behavior remains unchanged; its marker digest becomes ciphertext.
- No PWA durable fan-out runs in the first slice.
- Body-free safety telemetry continues when transcript retention is denied.
- The slice cannot modify safety triage, clinical data, memory roots, Hermes, or live configuration.

## 10. Current run definition of done

This run is complete only when:

1. v2 architecture and change spec receive fresh independent PASS results;
2. every selected implementation ticket has a failing test before code and passes after code;
3. baseline and focused suites pass without protected regression;
4. independent standards and spec reviews report no unresolved blocker or major defect;
5. accepted commits stay within repository and budget boundaries;
6. no live activation or clinical-data operation occurred;
7. the final report says the full product program remains incomplete and names the next human gate.
