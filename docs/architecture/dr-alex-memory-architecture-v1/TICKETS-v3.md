# Dr. Alex memory safety v3 implementation tickets

**Status:** Candidate tickets; not ready until v3 review PASS  
**Commit budget:** one implementation commit per repository  
**Parallelism:** tickets may run in parallel only in separate clean worktrees

## DA-SEC-001: Encrypt the existing TUI recovery digest

**Repository:** `praxstack/dr-alex`  
**Priority:** P0 privacy  
**Blocked by:** v3 specification approval  
**Owns:** `dr_alex/statefile.py`, `dr_alex/fanout.py`, `tests/test_fanout.py`

### Outcome

Persist `UnfinalizedMarker.digest` only as Fernet ciphertext and migrate a legacy marker before
the first replayed sink call, without changing normal, non-conflicting fan-out behavior. A
different still-pending session deliberately fails closed before any sink.

### Acceptance

- [ ] A focused test fails because the legacy marker is plaintext before implementation.
- [ ] `set_unfinalized` persists `digest_enc` and no plaintext `digest`.
- [ ] Runtime dataclass shape and public caller signatures remain unchanged;
      `recover_if_needed` rewrites the marker before calling `complete`.
- [ ] Legacy plaintext loads and is rewritten before the first injected sink.
- [ ] Invalid ciphertext raises `crypto.CryptoError` and leaves recovery visibly pending.
- [ ] Malformed decrypted JSON, a decrypted non-object, and ciphertext-plus-plaintext fallback
      attempts fail loudly; invalid UTF-8 and invalid encrypted envelope fields also raise
      `crypto.CryptoError`; encryption failure preserves exact prior bytes.
- [ ] A different session raises the exact built-in `RuntimeError` from the raw-session guard;
      a forbidden-decrypt spy proves it cannot decrypt, replace the marker, or call any sink.
- [ ] The statefile module text no longer calls the derived digest metadata-only/non-clinical.
- [ ] Existing fan-out idempotency tests pass.
- [ ] Changed-file lint, format, and mypy pass.
- [ ] Full Dr. Alex suite and version smoke pass.
- [ ] Independent code review has no unresolved blocker or major finding.

### Rollback

Revert the single Dr. Alex commit after proving no pending v3 marker exists in the test worktree.
A corrupt/wrong-key marker blocks rollback and requires key restoration or separate human
incident authority; it is never cleared for convenience. No live marker is touched by this run.

## AM-SEC-001: Remove legacy request authority for high sensitivity

**Repository:** `praxstack/agent-memory`  
**Priority:** P0 authorization  
**Blocked by:** v3 and OpenSpec approval  
**Owns:** recall/MCP authorization, affected tests, and the OpenSpec change only

### Outcome

Treat `include_sensitive` as a compatibility request for high scope and route it through the
existing high-ceiling authorization before recall/index or MCP document access.

### Acceptance

- [ ] OpenSpec updates `derived-index` and `mcp-transport` policy.
- [ ] A focused general-client test fails by exposing the current bypass before implementation.
- [ ] Recall normalizes legacy high to the existing ceiling authorization.
- [ ] MCP `get_memory` authorizes legacy high before `fetch_document`.
- [ ] MCP tool descriptions say the compatibility flag requests authorized high scope and is not
      permission.
- [ ] General, hook, missing, and spoofed clients cannot grant themselves high access.
- [ ] Direct `agent="codex", is_cli=False` legacy-high recall refuses before index open.
- [ ] Refusal-before-read tests pass.
- [ ] Human CLI, `dr-alex`, low, and medium compatibility tests pass.
- [ ] Existing index/trust tests use explicit authorized identities, and the stale-revision test
      still proves fetch was reached and pins the existing exit-10/message wire shape.
- [ ] Archived canonical parent requirements contain no Boolean-as-permission wording.
- [ ] Full hermetic agent-memory suite passes.
- [ ] No live corpus, index, scheduler, service, or memory file changes.
- [ ] Independent code review has no unresolved blocker or major finding.

### Rollback

Revert the single agent-memory commit containing implementation and archived OpenSpec changes.
No data migration exists.

## PWA-POLICY-001: Approve retention and lifecycle policy

**Repository:** planning only  
**Priority:** blocked  
**Ready for agent:** no  
**Owner:** human product/privacy decision

### Required decision

Approve the exact consent, retention, withdrawal/deletion, sink, RED, abandoned-tab, overlap,
restart, backup/restore, rollback, and activation rules in `ARCHITECTURE-v3.md` Stage 1.

### Explicit non-acceptance

No consent table, feature flag, synthetic finalizer, device-owner schema, or PWA fan-out code is
evidence of completion. A new versioned run contract and evaluator are required after the human
decision.

## TUI-POLICY-001: Resolve existing legacy durable retention

**Repository:** planning only  
**Priority:** blocked  
**Ready for agent:** no  
**Owner:** human product/privacy decision

### Required decision

Explicitly accept existing TUI fan-out under a versioned purpose, consent, retention,
withdrawal/deletion, sink, backup/restore, RED, rollback, and activation policy; change it; or
disable it. Preserving the baseline in v3 is containment and makes no compliance claim.

## RELEVANCE-SPEC-001: Clarify the independent active ranking contract

**Repository:** `praxstack/agent-memory` planning only  
**Priority:** separate active-change defect  
**Ready under v3:** no  
**Owner:** `improve-recall-relevance`

Clarify whether a single source bucket may exceed the diversity cap when no alternate bucket can
fill `k`, and make the final stable-ID tie-break normative with a tie-case test. V3 neither
archives nor approves those unrelated ranking clauses; it changes only their carried sensitivity
policy.

## Dependency graph

```text
v3 review PASS
  |-- DA-SEC-001 -> Dr. Alex review -> Dr. Alex commit
  `-- AM-SEC-001 -> OpenSpec approval -> agent-memory review -> agent-memory commit

PWA-POLICY-001 --human approval--> later PWA lifecycle run
TUI-POLICY-001 --human approval--> later TUI retention run or documented acceptance
RELEVANCE-SPEC-001 --owning change--> ranking-spec clarification and tie test
```
