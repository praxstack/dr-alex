# Dr. Alex Memory Architecture v1 — Run Contract

**Frozen at:** 2026-08-23T13:43:26Z  
**Run class:** LARGE, multi-repository, identity-preserving  
**Status:** Active implementation run; activation and clinical-data migration remain gated

## 1. Product objective

Implement the minimum existing-platform architecture that gives every authorized Dr. Alex conversation one auditable lifecycle across supported surfaces while preserving safety, privacy, provenance, correction, deletion, and explicit retention consent.

Product completion means the implementation tickets in this program are individually verified and committed, and the final integration suite proves:

1. A supported retained conversation reaches exactly one idempotent processing lifecycle.
2. Raw transcripts, derived memory, and prompt context remain distinct layers.
3. Clinical memory is physically isolated, encrypted, authenticated, and inaccessible to non-therapy clients outside the approved API.
4. Current-turn crisis triage remains independent of memory and preserves all existing Dr. Alex safety invariants.
5. Recall excludes stale, unauthorized, deleted, invalid, and context-inapplicable memories.
6. User-facing inspect, correct, forget, export, and reset operations have enforceable contracts.
7. No graph, embedding, model, network service, or new memory product is required for the canonical write path or BM25 fallback.

## 2. Governing baseline

Human-approved evidence inputs are immutable during this run:

- `therapist-stack-audit-2026-08-22.html`
  - SHA-256: `d349628361212722c06901b365dfc81d135fb4279e9655f9b5947d2a4c6e9005`
- `dr-alex-memory-architecture-review-2026-08-23.html`
  - SHA-256: `1cc6e53eab0d1a7509f13d3aaf06db7c384d5d27fc382d3b47cf82a81372320c`
- Independent adversarial reverification:
  - `/Users/prax/Documents/Hermes-Reports/research-dr-alex-memory-architecture-20260823/waves/wave-03/adversarial-reverification.md`
  - Verdict: PASS

Repository baselines:

- `dr-alex`: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`
- `agent-memory`: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`
- `therapy-stack`: `9ce6054195366eb57b414ecd51b087487cdd22c5` (reference only; no implementation changes)

## 3. Protected controls and paths

The following may not change in this run:

- This run contract, the two governing reports, their research evaluator, thresholds, or evidence policy.
- `/Users/prax/Developer/agent-stack/policies/identity-preservation.md`.
- Private conversation content, clinical archives, therapist `state.db`, clinical source records, and backup archives.
- Therapist profile `SOUL.md`, `USER.md`, `MEMORY.md`, `.env`, `config.yaml`, gateway state, Telegram routing, and cron activation.
- Dr. Alex triage-first, RED short-circuit, single-LLM-entrypoint, golden RED-recall, frozen-section integrity, deterministic output gates, encryption-at-rest, and loopback-only invariants.
- Agent-memory canonical-authority, single-writer flock, supersede/quarantine/archive-by-default, fail-loud index state, and BM25-without-optional-services invariants.
- Existing unrelated dirty files in `/Users/prax/agent-memory` and `/Users/prax/therapy-stack`.

Changes to any protected item require a separately approved governing version. Tests that encode these controls may be extended but not weakened or rewritten to make a candidate pass.

## 4. Permitted mutable surfaces

Only isolated feature worktrees may be modified:

- `/Users/prax/Development/Hermes-Projects/dr-alex-memory-architecture-v1`
  - architecture/specification documents;
  - standalone session lifecycle and transport wiring;
  - synthetic tests and content-free telemetry;
  - user-control interfaces that do not activate external state.
- A separately created `agent-memory` worktree from baseline `a01bc4c`:
  - OpenSpec change artifacts;
  - physical-root routing and authenticated client boundary;
  - removal of the legacy high-sensitivity bypass;
  - synthetic isolation tests.
- A standalone Hermes plugin repository or plugin fixture only if live Hermes hooks cannot consume the stable event contract. Hermes core remains unmodified unless a fresh, explicit architecture revision approves it.

## 5. Frozen evaluator and holdout

Acceptance evidence is fixed before implementation:

- Existing full test suites in `dr-alex` and `agent-memory` at the baseline commits.
- Existing Dr. Alex golden crisis corpus and immutable safety tests.
- Existing agent-memory keyword and natural-language golden sets; failures are carried as baseline defects, not hidden or weakened.
- The 60-case synthetic Memory Torture Deck and 12-trajectory crisis pack described in the verified research workspace.
- New tests may cover newly specified behavior, but the candidate cannot edit their acceptance thresholds after seeing results.
- No private clinical text may enter fixtures, logs, reports, or model-review prompts.

Candidate acceptance requires comparison with both the original repository baseline and the current accepted candidate, strict improvement on the target behavior, and no protected regression.

## 6. Budgets and stop rule

- Maximum implementation commits in this run: `8` across repositories.
- Maximum independent review/fix rounds per implementation slice: `5`.
- Maximum candidate diff: `1500` net changed lines per repository before a new scope review.
- Maximum parallel external reviewers per gate: `6`.
- Stop after the first hard budget limit or after `2` consecutive candidates produce no held-out improvement.
- Do not weaken a gate, alter a holdout, broaden “done,” or extend the budget to avoid reporting a stall.

## 7. Commit and activation boundary

This run authorizes local feature branches and verified commits. It does not authorize:

- merging to `main`;
- pushing or opening a public pull request containing sensitive architecture details;
- restarting or reconfiguring the therapist gateway;
- activating a Hermes hook/plugin against live therapy sessions;
- migrating, copying, decrypting, deleting, or purging clinical data;
- changing Telegram, backup, credential, retention, or clinical policy state.

Those operations retain the standing human gate. Local GitHub issues may contain only privacy-safe implementation contracts and synthetic acceptance criteria.

## 8. Rollback pointers

- Dr. Alex worktree rollback: `git reset --hard e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`.
- Agent-memory worktree rollback: `git reset --hard a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`.
- No rollback command may be run against the original dirty working trees.

## 9. First tracer bullet

The first implementation slice is the smallest existing-code change that improves product behavior without crossing another gate:

> Every standalone Dr. Alex PWA session-end request uses the existing `fanout.finalize_session` lifecycle, records an idempotent receipt, and leaves the crash marker intact on partial failure so recovery retries safely.

This slice must be test-first, must route through the existing finalization seam, and must not modify safety triage, memory authorization, live clinical data, or Hermes configuration.
