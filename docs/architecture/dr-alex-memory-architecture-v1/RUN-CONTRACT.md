# Dr. Alex Memory Architecture v5 Run Contract

**Frozen at:** 2026-08-23T16:17:23Z  
**Run class:** LARGE, multi-repository, identity-preserving  
**Status:** Governing baseline frozen; implementation blocked until exact-hash candidate PASS  
**Supersedes:** rejected v4 contract preserved as `RUN-CONTRACT-v4-rejected-20260823.md`  
**Authorization:** The user explicitly authorized fixing the remaining wording and continuing through implementation. V5 carries that approval forward for the four confirmed v4 review leftovers only.

## 1. Product identity

### Objective

Build the minimum existing-platform increment that establishes consent-governed, identity-bound, auditable Dr. Alex memory lifecycle primitives without claiming or activating universal cross-surface continuity.

### Full-program success definition

The full product program is complete only after later human-gated stages prove:

1. Every supported retained conversation reaches one idempotent lifecycle.
2. Raw transcripts, derived memory, and prompt context remain distinct.
3. Clinical storage is physically isolated, separately encrypted, authenticated, and unavailable to non-therapy clients outside an approved API.
4. Current-turn crisis triage remains independent of memory and preserves every existing safety invariant.
5. Recall excludes stale, unauthorized, deleted, invalid, and context-inapplicable memories.
6. User inspect, correct, forget, export, and reset operations are enforceable.
7. Deletion propagates through canonical storage, indexes, WAL, caches, backups, and restore manifests.
8. The encrypted standalone PWA remains available until replacement parity is proven.

### Accepted increment for this run

This run may deliver only:

- always-on paired-device ownership for PWA sessions;
- default-off, explicit consent receipts and transcript policy;
- encrypted migration of the existing TUI marker digest;
- encrypted per-session synthetic PWA operation records;
- one marker-free completion seam shared by legacy and synthetic paths;
- no new live PWA durable sink;
- removal of request fields as authority for high-sensitivity recall snippets and full-body reads;
- synthetic tests, local documentation, and bounded local commits.

This increment is not product completion, physical clinical isolation, deletion completion, Hermes integration, or activation.

## 2. Immutable governing baseline

### Human-approved content-free evidence

- `GOVERNING-EVIDENCE-v3.md`
- SHA-256: `ee2a8370ad9024bdb416d1660753d0d6f4623ef3ae7ebfab42c26f9f2a2f4296`

### Frozen evaluator

- `EVALUATOR-v3.md`
- SHA-256: `e53fd42c28c609c8f36684df6d39a7932bf97b9f40b6bb911227303eccecd710`
- Contains 63 unique synthetic outcomes plus full-suite and protected-control gates.

### Repository baselines

- Dr. Alex: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`
- agent-memory: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`
- Hermes: `d5281f59819d2ea2ce6754faec2ce317c92366c8`, reference only
- therapy-stack: `9ce6054195366eb57b414ecd51b087487cdd22c5`, historical reference only

### Restricted historical sources

The original narrative reports remain preserved in place as restricted clinical references. They are not governing inputs for v5. They must not be copied, quoted, committed, published, or sent to external reviewers.

### Review evidence

Review receipts remain outside candidate hashes:

- `reviews/codex-review.md`
- `reviews/grok-review.md`
- `reviews/plan-and-council-synthesis.md`
- `REVIEW-FINDINGS.md`
- `verification-receipt.md`

## 3. Candidate baseline and comparison rule

The initial v5 baseline is the rejected v4 candidate:

- `ARCHITECTURE.md`: `15925fc24590bff42ec7bcdbd564e2af4ff337dc952b8c7869a4465e668b7a39`
- `CHANGE-SPEC.md`: `8c496f8af5c626deed5cedecf4eea5cbe40a6267ab026d2a63a92b18574ee5e9`

Every later candidate must be compared with:

1. the repository baselines;
2. this initial v4 baseline;
3. the current accepted candidate.

A candidate may change architecture, change spec, code, and tests only within permitted paths. It may not change this contract, the governing evidence, evaluator, thresholds, protected controls, or evidence policy.

Candidate acceptance requires strict held-out improvement on the target behavior with no protected regression. Edited evaluator outcomes are not acceptance evidence.

### One authorized document repair

V5 authorizes one candidate that may only:

1. replace stale `v2` and `v3` stage, subject, and definition-of-done labels with `v5`;
2. state in architecture that every body-free terminal operation has null lease owner and expiry;
3. make additive regression `RC4-R03` assert both null payload and null lease fields;
4. restate that legacy pending-fragment drain applies only to a live session.

No other architecture, evaluator, scope, product, or activation change is allowed in the document-repair candidate.

## 4. Protected controls and paths

The following cannot change in this run:

- `RUN-CONTRACT.md`, `RUN-CONTRACT-v3-stopped-20260823.md`, `RUN-CONTRACT-v4-rejected-20260823.md`, `GOVERNING-EVIDENCE-v3.md`, and `EVALUATOR-v3.md` after this freeze;
- `/Users/prax/Developer/agent-stack/policies/identity-preservation.md`;
- restricted reports, private conversation content, clinical archives, therapist `state.db`, clinical source records, and backup archives;
- therapist `SOUL.md`, `USER.md`, `MEMORY.md`, `.env`, `config.yaml`, gateway state, Telegram routing, and cron activation;
- Dr. Alex triage-first ordering, RED short-circuit, single LLM entry point, golden RED-recall, frozen sections, deterministic output gates, encryption-at-rest, and loopback-only controls;
- agent-memory canonical authority, single-writer flock, supersede, quarantine, archive-by-default except where a later human-approved erasure contract overrides it, fail-loud index state, and BM25 without optional services;
- unrelated dirty files in original Dr. Alex, agent-memory, therapy-stack, and Hermes worktrees.

Tests may extend coverage but cannot weaken frozen outcomes or rewrite expected behavior to make a candidate pass.

## 5. Permitted mutable paths

Only clean isolated feature worktrees may change.

### Dr. Alex worktree

`/Users/prax/Development/Hermes-Projects/dr-alex-memory-architecture-v1`

Allowed:

- architecture, change-spec, ticket, review, and receipt documents other than the frozen v3 governing files;
- local consent and paired-device session ownership;
- transcript policy at the existing shared turn seam;
- encryption migration for the legacy TUI marker digest;
- encrypted per-session synthetic finalization operations in existing `state.db`;
- marker-free completion extraction shared by legacy and synthetic paths;
- default-off PWA lifecycle wrapper with synthetic sinks only;
- focused synthetic tests and body-free telemetry.

Prohibited:

- safety-triage or crisis-content changes;
- a new live PWA durable write;
- new Notion, Active File, inbox, continuity, canonical-memory, backup, or network output;
- live state, clinical records, corpus, secrets, or activation.

### agent-memory worktree

Use a separate clean worktree from `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`.

Allowed:

- removal of `include_sensitive` as an authorization mechanism for recall and full-body fetch;
- same-descriptor metadata-first authorization for full-body fetch;
- focused synthetic authorization tests;
- local OpenSpec and threat-model notes.

Prohibited:

- clinical-root, key, OS identity, service, socket, daemon, or live-policy creation;
- claims of physical clinical isolation;
- moving, decrypting, importing, deleting, or rewriting memory content;
- repair of operational doctor defects unless separately approved.

### Hermes and therapy-stack

No source, profile, configuration, data, or service edit is allowed. Both are read-only references.

## 6. Frozen evaluator and thresholds

Acceptance evidence is fixed in `EVALUATOR-v3.md`:

- all 63 named synthetic outcomes pass;
- both full repository suites pass;
- no protected control regresses;
- no private clinical content appears in fixtures, logs, tickets, reports, or review prompts;
- independent standards and spec reviews report zero blocker and zero major defect;
- `memctl doctor` exit 7 remains a carried baseline defect unless a separately approved run repairs it;
- the v4 baseline and every later candidate remain inside the diff and commit budgets.

The candidate cannot modify `EVALUATOR-v3.md`, its expected outcomes, or these thresholds.

## 7. Budgets and stop rule

- Maximum implementation commits: `8` across repositories.
- Planned implementation commits: `6`.
- Maximum document-repair candidates before implementation: `1`.
- Maximum independent review/fix rounds per implementation slice: `5`.
- Maximum implementation and test diff: `1500` net changed lines per repository relative to the repository baseline; governing, review, receipt, and generated HTML files are excluded from this implementation budget.
- Maximum parallel external reviewers per gate: `6`.
- Maximum new external reviewer invocations after this freeze: `12`.
- Maximum active implementation elapsed time: `12 hours`.
- Cost budget: no new paid service, subscription, credential, or provider spend; use already configured tools only.
- Stop the document phase immediately if the one authorized repair candidate does not receive exact-hash PASS with zero blocker and zero major finding.
- After document PASS, stop an implementation slice at the first hard budget limit or after `2` consecutive code candidates produce no held-out improvement.
- Do not weaken a gate, change a holdout, broaden done, or extend a budget to hide a stall.

Document-only governing-version work before this freeze does not count as implementation commits.

## 8. Commit and activation boundary

This run authorizes isolated feature branches and verified local commits. It does not authorize:

- merge to `main`;
- public push or pull request;
- therapist gateway restart or configuration;
- live Hermes hook or plugin;
- real clinical data migration, copy, decryption, deletion, purge, or export;
- Telegram, backup, credential, retention, OS-user, service, socket, key, or clinical-policy changes;
- live PWA durable finalization.

Those operations retain separate human gates.

## 9. Rollback pointers

- Dr. Alex code rollback: `git reset --hard e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d` in the isolated worktree.
- agent-memory code rollback: `git reset --hard a01bc4cb9697aaeff69671d82ea2dbca1f32cd38` in its isolated worktree.
- Governing-contract rollback: `RUN-CONTRACT-v4-rejected-20260823.md`, SHA-256 `26feada532ba19977c72ba3b9de51b6f8b8848ab23784c1ec320e7b6fd25e59e`.
- Never run rollback commands in original dirty worktrees.

## 10. First tracer bullet

The first implementation slice is test-first and makes one intentional default security change: PWA session ownership becomes device-bound. Consent enforcement and PWA durable finalization remain default-off. Existing TUI sink behavior remains unchanged; only its marker digest becomes ciphertext.

The slice must:

1. resolve one stable local subject and verified paired-device actor;
2. always bind PWA start, turn, check-in, and end to the owner;
3. persist explicit default-deny consent receipts outside the telemetry kill-switch;
4. suppress transcript rows under explicit `deny` in the isolated enforcement profile;
5. retain body-free safety telemetry where enabled;
6. run no live PWA fan-out and touch no clinical data or live configuration.

## 11. Current run definition of done

This run is complete only when:

1. the exact architecture and change-spec candidate receives fresh independent PASS results under this content-free v5 contract and unchanged v3 evidence/evaluator;
2. ordered tickets map every selected change to frozen evaluator IDs;
3. every ticket has a failing test before implementation and passes after implementation;
4. both full suites pass without protected regression;
5. independent standards and spec reviews report no blocker or major defect;
6. accepted commits stay within repository, diff, time, and count budgets;
7. no live activation, clinical-data operation, external publication, or restricted-source disclosure occurred;
8. the final report distinguishes the accepted increment from the incomplete full product and names the next human gate.
