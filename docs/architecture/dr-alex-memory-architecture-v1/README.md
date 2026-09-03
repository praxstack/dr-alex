# Dr. Alex memory architecture review artifacts

The current review candidate is v3 with the user-authorized v3.2 review-budget revision.
Authority is explicit:

| Artifact | Role |
|---|---|
| `RUN-CONTRACT-v3.md` | Governing v3.2 scope, evaluator, review budget, rollback, and activation boundary after approval |
| `ARCHITECTURE-v3.md` | Governing architecture boundary after approval |
| `CHANGE-SPEC-v3.md` | Governing implementation contract after approval |
| `../../adr/0001-memory-retention-gate.md` | Accepted decision candidate; governing only after the exact-hash approval receipt |
| agent-memory OpenSpec delta | Governing authorization behavior after approval |
| `TICKETS-v3.md` | Subordinate execution plan; cannot override the governing files |
| `RESEARCH-EVIDENCE.md` | Non-authorizing library and future-policy evidence |
| `reviews/v3/` | Review and authorization receipts outside the governing content hash |

The unversioned `ARCHITECTURE.md`, `CHANGE-SPEC.md`, and `RUN-CONTRACT.md` are the
preserved v2 rc3 candidate produced by the earlier Hermes run. They are review history, not
implementation authority. The rc1 Codex and Grok reports under `reviews/` are failed-review
evidence, not approvals.

The original reports are restricted historical provenance. Fresh reviewers receive these
content-free v3 artifacts and exact hashes, not report bodies or private clinical material.

Implementation remains blocked until the v3.2 normative files receive fresh council, CEO,
engineering, design, DevEx, and final conformance approval on exact bytes. Codex, Grok, and MoA
verdicts are used when available; the active user goal requires any unavailable named model to be
replaced by Codex Luna XHigh on the same bytes and role lens. Activation, migration, and live
clinical-data operations remain prohibited.
