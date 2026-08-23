# V3 specification approval receipt

**Status:** APPROVED FOR LOCAL IMPLEMENTATION  
**Approved at:** 2026-08-23T17:52:05Z  
**Scope:** the two repairs in the v3.2 run contract only

## Baselines

- Dr. Alex: `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`
- agent-memory: `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`

## Governing hash freeze

| Artifact | SHA-256 |
|---|---|
| `RUN-CONTRACT-v3.md` | `0bc65c6f87c9a747c538ae14e6506d7fc23b72d51f0ce94d86feee0343f30537` |
| `ARCHITECTURE-v3.md` | `ff88419d0f6d96b7fe599cbc1ba91ebd71fc32e496708acddb543d8823dccaf9` |
| `CHANGE-SPEC-v3.md` | `5405fc0468f87875bcfb8e460355915acff1025bdd759654432e268b2cd16196` |
| `docs/adr/0001-memory-retention-gate.md` | `e456782f26ca6b6f04ff356da7a42bf8daf9cb961abc71f404786325882d8648` |
| hardening `proposal.md` | `2f34895760eab9523ee3a176e3453dae9d6928872ab6906b02d7f799968a6336` |
| hardening `design.md` | `fe05849f7085b100c71842eb95735f69ff12e80f500a5f48ea631392302545b8` |
| hardening `specs/derived-index/spec.md` | `454bce5768dea8d1e1c46be80988d3a624b418d3370fd9a4e70ce1868970ce12` |
| hardening `specs/mcp-transport/spec.md` | `b6a231a3fd430da22fbf99120204e6aefd909fb0998e57036db473ffbd079d93` |

Archive relocation must preserve the four hardening hashes exactly. The whole-file integrity
hash for `improve-recall-relevance/specs/derived-index/spec.md` is
`6f49ac7ec97b2ca08300cb4f8319285b90cf35869bfa7fb3be22946e747ee68a`.
That hash protects the overlap during this run; approval remains limited to its sensitivity
paragraph and legacy-authorization scenarios, not its unrelated ranking clauses.

## Exact-byte verdicts

- Codex Luna XHigh final role-lens review: `FINAL SPEC PASS`, zero P0-P3 findings.
- Independent Codex Luna XHigh adversarial conformance review: `FINAL SPEC PASS`, zero P0-P3
  findings.
- CEO/product: PASS. Design/UX: N/A-PASS. Architecture, engineering, security/privacy, rollback,
  testability, DevEx, council, and final conformance: PASS.
- Strict OpenSpec: 15 passed, 0 failed. Standalone HTML repeat-render, semantic-body, asset, and
  CSS gates: PASS. Exact manifest extraction: 17 Dr. Alex and 15 agent-memory paths.

The active user goal authorizes Codex Luna XHigh to replace any unavailable named review model
on the same bytes and role lens. This receipt waives no finding, test, threshold, or review.
Earlier Codex, Grok, MoA, and subagent feedback is fully dispositioned in
`REVIEW-LEDGER-v3.md`; stale pre-R52 verdicts are not used as this hash approval.

## Decision

The implementation gate is open. Candidate code may change only the mutable paths and must be
tested against the frozen evaluator. Any change to a governing hash above invalidates this
approval and requires a new version and fresh review. Push, merge, deployment, activation,
migration, live-data access, and the blocked PWA/TUI policy decisions remain unauthorized.
