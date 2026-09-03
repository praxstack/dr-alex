# Plan and council review synthesis

**Reviewed candidate:** rc1 historical packet  
**Current disposition candidate:** `CHANGE-SPEC.md` `2.0.0-rc3`  
**Status:** implementation blocked pending final RC3 PASS

## Review results

| Review | Historical verdict | Decision-critical findings | RC3 disposition |
|---|---|---|---|
| CEO | No-go as written | consent did not control transcript writes; clinical writes preceded isolation; event-log scope was invented; nine tickets exceeded the budget | consent first; no new live sink; existing transcripts reused; physical isolation parked; six commits |
| Engineering | Changes required | Hermes hook had no transcript; PWA end path lacked reliable client trigger; one global marker; principal was self-asserted; status and recovery contracts conflicted | H1 parked; live PWA finalization disabled; legacy marker encrypted; PWA operations per-session and leased; one enum |
| Design | N/A | no in-scope UI implementation | accepted; consent copy and End Session UX require a later design and human gate |
| DevEx | 5.1/10, concerns | conflicting statuses, vague errors, missing operator state, plan/commit ambiguity | one status and HTTP map; named errors and recovery; six explicit commits; user-control and activation CLI work parked |
| Aristotle | reject sequence, accept direction | “minimum safe” requires consent, provenance, isolation, idempotency, and rollback before new clinical writes | D1 adds no live writer; M1-A is request-flag hardening only; isolation remains later |
| Ada | reject rc1 | consent and idempotency were not mechanized; request identity could be spoofed; marker was plaintext | 63 named synthetic tests; atomic create-or-load; resume lease; request flag is not authority; marker encrypted |
| Feynman | reject rc1 | transcript persistence bypass, multi-sink fan-out, plaintext marker, and unproven encryption boundary | enforced transcript seam; current sinks inventoried; marker cipher; physical boundary not claimed |

## Absorbed findings

1. Consent enforcement is default off and does not gate authentication.
2. PWA session ownership is always-on and covers start, turn, check-in, and end.
3. The default-off profile distinguishes `legacy`, `retain`, and `deny` transcript policy.
4. Durable memory depends on retained transcript provenance only under enforced consent.
5. The TUI marker digest becomes ciphertext without changing sink behavior.
6. PWA operations are per-session, encrypted, atomic, and resumable under a bounded lease.
7. The PWA runner uses marker-free `complete_digest` with synthetic sinks only.
8. Lifecycle status and HTTP behavior use one enum, including `finalization_unavailable`.
9. `include_sensitive` cannot authorize recall snippets or full bodies.
10. Full-body authorization parses bounded frontmatter and authorizes before reading the body from the same descriptor.
11. The run uses six repository-scoped implementation commits, below the frozen cap of eight.
12. H1, physical clinical isolation, graph/vector work, per-turn retrieval, deletion productization, user-control UI, migration, and activation are not ready tickets.

## Parked, not lost

### PWA completion UX

Current Room JavaScript does not expose a reliable End Session action and has no idle-expiry contract. This is not part of RC3 because live PWA durable finalization remains disabled. A later activation spec must include:

- accessible End Session control;
- retry-safe client receipt display;
- server-side idle expiry;
- page close and network-loss behavior;
- consent copy and withdrawal UX;
- a design review with real UI states.

### Physical clinical isolation

Same-UID process names and POSIX modes are not a clinical boundary. A later human-approved contract must define the process identity, encrypted store, key ownership, local transport, backup, restore, deletion, and live provisioning.

### Operations

`memctl doctor` still exits 7. RC3 does not claim it fixed. No live data is read or changed to repair it in this run.

## Final plan-review verdict

RC1 remains rejected. RC3 may proceed to tickets and implementation only after a fresh verifier checks the pinned RC3 hashes and returns PASS with no blocker or major finding.
