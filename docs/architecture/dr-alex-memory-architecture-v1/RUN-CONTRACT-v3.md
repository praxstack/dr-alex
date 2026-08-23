# Dr. Alex memory safety v3 run contract

**Status:** Frozen review candidate  
**Initial review freeze:** 2026-08-23T14:59:27Z  
**Review-budget revision:** v3.2, authorized by the active user completion goal at 2026-08-23T17:06:13Z; unavailable-model substitution authorized at 2026-08-23T17:38:38Z  
**Run class:** bounded, two-repository security repair  
**Implementation:** blocked until v3.2 exact-byte role-lens review PASS

## 1. Objective and success definition

Repair two verified existing exposures with the smallest working diffs:

1. encrypt and safely migrate the existing TUI crash-marker digest;
2. remove `include_sensitive` as independent authority for high-sensitivity agent-memory
   recall and MCP full-body reads.

Success is observable only when the named focused checks, both canonical full suites,
changed-file quality checks, and independent code reviews pass with no protected regression.
PWA lifecycle, consent infrastructure, physical isolation, deletion, and Hermes consolidation
are not success criteria for this run.

## 2. Immutable baseline and provenance inputs

- Dr. Alex: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`.
- agent-memory: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`.
- restricted therapist-stack audit provenance SHA-256:
  `d349628361212722c06901b365dfc81d135fb4279e9655f9b5947d2a4c6e9005`.
- restricted Dr. Alex memory-review provenance SHA-256:
  `1cc6e53eab0d1a7509f13d3aaf06db7c384d5d27fc382d3b47cf82a81372320c`.
- content-free research adversarial reverification verdict: `PASS`.
- identity-preservation policy:
  `/Users/prax/Developer/agent-stack/policies/identity-preservation.md`.

The report hashes preserve historical provenance; report bodies are not governing or externally
reviewable inputs. Reviewers receive only the content-free v3 artifacts. The current user's
end-to-end review/specify/implement instruction authorizes creation of this new content-free
candidate; `reviews/v3/AUTHORIZATION-AND-PROVENANCE.md` records that scope without publishing
private material. Review findings may refine this unapproved candidate and are recorded outside
its eventual content hash. The ADR status and every governing status string are finalized before
the last hash-bound conformance reviews. After those reviewers pass the exact bytes and before
the first production edit, an approval receipt records hashes for the run contract, architecture,
change spec, accepted ADR, and the four governing hardening OpenSpec files defined below. Those
hashes, the safety corpus, existing full-suite expectations outside the deliberate authorization
change, and acceptance thresholds then freeze for implementation.

The four-file governing OpenSpec set is
`harden-sensitive-request-authorization/{proposal.md,design.md,specs/derived-index/spec.md,specs/mcp-transport/spec.md}`.
Archive relocation must preserve those content hashes. The approval receipt also records a
whole-file integrity hash for
`improve-recall-relevance/specs/derived-index/spec.md`, but v3 approves only its sensitivity
paragraph and legacy-authorization scenarios; its unrelated ranking contract remains owned by
that active change. `.openspec.yaml` and `tasks.md` are execution receipts outside the governing
hash set; task checkboxes may change without changing policy.

## 3. Protected paths and controls

This run cannot change:

- Dr. Alex triage, crisis content, model entry point, output gates, books, PWA/Room source,
  transcript schema, normal/non-conflicting fan-out sink behavior, config, service files, or
  live data;
- Hermes, therapist profiles, Telegram routing, Therapy Stack, backups, credentials, clinical
  records, memory roots, services, or schedulers;
- agent-memory canonical memory files, write path, index architecture, gardener, provenance,
  supersession, quarantine, archive, or default low/medium behavior;
- unrelated dirty files in the original repositories.

No test or document may expose private conversation or clinical content.

Before implementation, create a fresh Dr. Alex worktree at frozen baseline
`e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`, transfer only the governed v3 document
manifest into it, and prove that every resulting path is allowed by Section 4. The contaminated
review worktree and its unrelated edits remain protected and are never staged, reverted, or
copied into the implementation worktree.

## 4. Mutable paths

### Dr. Alex isolated worktree

- `docs/adr/0001-memory-retention-gate.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/README.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/RUN-CONTRACT-v3.md` and `.html`;
- `docs/architecture/dr-alex-memory-architecture-v1/ARCHITECTURE-v3.md` and `.html`;
- `docs/architecture/dr-alex-memory-architecture-v1/CHANGE-SPEC-v3.md` and `.html`;
- `docs/architecture/dr-alex-memory-architecture-v1/TICKETS-v3.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/RESEARCH-EVIDENCE.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/AUTHORIZATION-AND-PROVENANCE.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/REVIEW-LEDGER-v3.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/SPEC-APPROVAL-v3.md`;
- `docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/CODE-REVIEW-v3.md`;
- `dr_alex/statefile.py`;
- `dr_alex/fanout.py`;
- `tests/test_fanout.py`.

### agent-memory isolated worktree

- the six files under
  `openspec/changes/harden-sensitive-request-authorization/` named in its current tree, or the
  same six files at
  `openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/` after archive;
- `openspec/specs/derived-index/spec.md` and `openspec/specs/mcp-transport/spec.md` as the
  archive-generated canonical updates;
- `openspec/changes/improve-recall-relevance/specs/derived-index/spec.md`, only for the
  sensitivity-policy paragraph and scenarios that keep the active delta policy-rebased;
- `tools/memctl/memctl/recall.py`;
- `tools/memctl/memctl/mcp.py`;
- `tests/test_mcp.py`;
- `tests/test_recall.py`;
- `tests/test_index.py`;
- `tests/test_index_trust.py`.

Any additional production file requires a new scope review before editing.

## 5. Frozen evaluator

The evaluator consists of:

- the test cases and behavior matrix named in `CHANGE-SPEC-v3.md` before candidate code;
- the existing Dr. Alex full suite and safety invariants;
- the existing agent-memory full hermetic suite;
- Dr. Alex changed-file ruff format/lint and source-file mypy checks;
- agent-memory's repository-native strict OpenSpec, compile, and hermetic pytest gates (that
  repository deliberately has no ruff or mypy dependency);
- baseline-relative global format and mypy results for Dr. Alex;
- diff/body/secret scans and independent specification and code reviews.

The deliberate agent-memory expectation change is authorized by the current user's direct
instruction and, after approval, this new versioned OpenSpec policy before code. The restricted
reports remain historical provenance and do not govern the candidate. No other expected result
may change to make a candidate pass. Every implementation candidate is compared with the
original baseline above and the current accepted version; until the first acceptance, those are
the same commit.

## 6. Budgets and stop rule

- Maximum implementation commits: `2`, one per repository.
- Maximum review/fix rounds per repository: `3`.
- Maximum net application-and-test diff: `400` changed lines per repository.
- New runtime dependencies, tables, flags, services, keys, or sinks: `0`.
- Elapsed-time ceiling: `8 hours` from the initial review freeze, ending
  `2026-08-23T22:59:27Z`.
- Model-compute ceiling: `1,500,000` reported or estimated tokens across fresh external review and
  implementation-agent runs. The user-authorized v3.2 amendment permits exactly one fifth
  exact-byte invocation each for Codex and Grok and one fourth MoA invocation. Every other CLI
  that exposes no token count remains capped at three invocations per named reviewer.
- A named model's unavailability, payment failure, or tool failure cannot block this run. The
  active user goal requires the affected review to be replaced by a Codex Luna XHigh review of
  the same exact bytes and role lens. This substitution changes neither the evaluator nor the
  scope, cost, token, round, or quality thresholds.
- Incremental metered-cost ceiling: `US$25`; subscription-included calls count as zero
  incremental spend only when the tool reports no separate charge.
- Stop after two consecutive candidates show no target improvement, at any budget limit, or on
  any protected regression. Report the stall; do not weaken a gate or expand scope.

Documentation and generated HTML are receipts, not product progress and do not increase the code
budget.

## 7. Rollback and activation boundary

- Dr. Alex rollback pointer: baseline commit above plus the v3 feature commit's parent.
- agent-memory rollback pointer: baseline commit above plus the v3 feature commit's parent.
- Revert only inside isolated worktrees; never run destructive rollback in original dirty
  checkouts.
- A valid pending encrypted Dr. Alex marker must be completed with v3 before reverting to pre-v3
  code. A wrong-key or corrupt marker blocks rollback: preserve its exact bytes, keep v3 in place,
  restore the correct key if possible, and require a separately authorized human incident
  decision if recovery remains impossible. Never clear or rewrite it merely to permit rollback.

The run authorizes local feature branches, private GitHub implementation tickets after spec
approval, and local commits after final review. It does not authorize push, merge, pull request,
deployment, restart, activation, live configuration, clinical-data access, migration, deletion,
or backup operation.

The post-commit final user handoff, outside either repository and therefore outside the commit
hashes it attests to, must report both baselines, both accepted commit IDs, protected-path diffs,
measured gains or regressions, budget consumed, rejected candidates, unresolved blocked policy
tickets, and exact non-destructive rollback commands. No self-referential final-delivery file is
staged.
