# Dr. Alex Memory Architecture v3 Stall Report

**Status:** V3 stopped by the frozen two-no-gain rule  
**Date:** 2026-08-23  
**Product state:** No application implementation started  
**Activation state:** Unchanged and prohibited

## 1. Identity

The objective was to establish an implementable, independently verified architecture for consent-governed, identity-bound, provenance-aware, temporal Dr. Alex memory continuity, then implement only the default-off D1 and request-flag M1-A slices.

Success required exact-hash independent PASS with zero blocker and zero major finding before tickets or code.

Application baselines remain:

- Dr. Alex: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`
- agent-memory: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`

## 2. Frozen v3 boundary

| Artifact | SHA-256 |
|---|---|
| `RUN-CONTRACT.md` | `2b6ee3db3bf29b3550869a8b2b83130932b8606b8bf1a240cbd683ccce53fc62` |
| `GOVERNING-EVIDENCE-v3.md` | `ee2a8370ad9024bdb416d1660753d0d6f4623ef3ae7ebfab42c26f9f2a2f4296` |
| `EVALUATOR-v3.md` | `e53fd42c28c609c8f36684df6d39a7932bf97b9f40b6bb911227303eccecd710` |

The restricted narrative reports remained non-governing and were not shared with the v3 reviewers.

## 3. Candidate results

| Candidate | Exact hashes | Independent result | Disposition |
|---|---|---|---|
| RC3 | Architecture `21d2b8ad…ddf5`; spec `76ef8820…35f` | Codex FAIL; Grok FAIL | Rejected |
| RC4 | Architecture `dee6e991…a7e3`; spec `29f65682…14e7` | Codex FAIL; Grok FAIL | Rejected and retained as evidence |

All 63 frozen evaluator outcomes remained byte-identical. RC4 added eight candidate regressions without changing the evaluator.

## 4. RC4 material failure

RC4 still contains incompatible consent and lease ordering:

1. Architecture requires current consent to be resolved before a resume claim.
2. Change-spec algorithm claims the operation lease first and resolves current consent afterward.
3. The architecture does not require current-consent re-resolution before every sink step, while the change spec does.

This leaves multiple conforming implementations for withdrawal during recovery and fails the zero-major threshold.

## 5. Additional unresolved wording defects

A future human-approved run would need to address all of these without changing the v3 evidence or 63-outcome evaluator:

- rename the architecture title from v2 to v3;
- gate pending-fragment drain explicitly to a live session;
- state one authoritative diff-budget comparison point and exclusion rule;
- explicitly clear lease fields on writer-disabled terminal creation;
- replace Turn wording that says End uses the cached policy with current-consent re-resolution;
- place consent resolution before compare-and-swap claim, then require re-resolution and fencing before every sink step.

## 6. Stop-rule application

The frozen v3 rule requires a stop after two consecutive candidates without held-out improvement. RC3 and RC4 both received material exact-hash FAIL verdicts. No RC5 is authorized in v3.

This report records the stall instead of weakening the threshold, editing the evaluator, expanding the review budget, or starting implementation against an unapproved spec.

## 7. Product, method, and library state

| Class | State |
|---|---|
| Product | No application source change; no live continuity improvement shipped |
| Method | Content-free v3 governance, 63-outcome evaluator, review ledger, and exact-hash receipts exist |
| Library | Restricted reports remain preserved but non-governing |

Method work is not reported as product progress.

## 8. Rollback and preserved evidence

- Application rollback: unchanged baseline commits above.
- Prior governing rollback: `RUN-CONTRACT-v2.md` hash `a8ec61fac2cf36e185d6e643138953a9ab55b5b836281cdc7f3f7c67fd35f091`.
- Active v3 governing baseline remains frozen at the hashes in section 2.
- Rejected RC4 remains in `ARCHITECTURE.md` and `CHANGE-SPEC.md` for audit.
- Separately named `*-v3` and `TICKETS-v3.md` artifacts with different hashes are unreviewed concurrent artifacts and are not accepted, published, or used for implementation.

## 9. Current proof

- No application source file changed in this run.
- No Hermes configuration, therapist profile, Telegram route, clinical record, memory service, or live sink was changed or activated.
- `memctl doctor` remains exit 7.
- Ticket publication, implementation, review loops, and commits are not started.

## 10. Human gate for any continuation

Continuation requires an explicit human-approved new run version. That approval must state whether the new run may make one bounded wording-repair candidate while preserving the v3 evidence, evaluator, thresholds, protected paths, application baselines, and activation prohibitions.
