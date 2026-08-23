# V3 specification review ledger

This receipt is outside the governing content hash. `Closed` means the current review candidate
contains the disposition; implementation remains blocked until fresh reviewers pass the exact
revised packet.

| ID | Source/severity | Finding | Disposition | Status |
|---|---|---|---|---|
| R1 | Architecture subagent P1 | Run contract lacked elapsed/token/cost budgets, baseline/current comparison, and required handoff fields | Added bounded budgets, dual comparison, stop rule, and exact handoff receipt fields | Closed |
| R2 | Architecture subagent/Codex P1 | Marker tests omitted wrong-key, malformed JSON, non-object JSON, plaintext fallback, and encryption-failure branches | Frozen parameterized failure cases plus exact-byte/no-sink encryption-failure test | Closed |
| R3 | Architecture/engineering/MoA/Codex P2 | One-commit budget conflicted with separate implementation/archive rollback text | One atomic agent-memory commit now contains code, tests, canonical specs, and archive | Closed |
| R4 | Architecture subagent P2 | MCP descriptions implied the Boolean granted high access | Spec and ticket require compatible fields with descriptions that say authorized high scope is required | Closed |
| R5 | Architecture subagent P2 | Existing TUI retention had no executive disposition | Added blocked `TUI-POLICY-001`; legacy behavior is containment, not consent acceptance | Closed |
| R6 | Architecture/engineering P3 | `statefile.py` falsely called the file metadata-only/non-clinical | The owned-file acceptance contract requires an accurate encrypted-digest/plaintext-metadata description | Closed |
| R7 | Engineering P1 | Spec claimed every request `agent` was only a filter, contradicting direct CLI/Python label trust | Scoped spoof resistance to MCP request bodies and documented accepted same-user direct-label trust | Closed |
| R8 | Engineering/Codex P1/P2 | Agent-memory ruff/mypy gates were unavailable and Dr. Alex omitted format check | Split repository-native evaluators; added Dr. Alex format and agent-memory OpenSpec/compile/render/full pytest | Closed |
| R9 | Engineering P2 | Existing stale-revision MCP test would pass at the new pre-fetch denial and become vacuous | Contract requires authorized `dr-alex` for that leg plus a separate before-fetch denial seam | Closed |
| R10 | Self/engineering/Codex P2 | OpenSpec omitted affected `test_index.py` and `test_index_trust.py` | Impact and tasks now name all four affected test files and their authority setup | Closed |
| R11 | MoA P2 | Ticket wording could imply no `recover_if_needed` change | Ticket now requires rewrite-before-`complete` while preserving runtime dataclass and public signatures | Closed |
| R12 | MoA/Codex P2 | OpenSpec reviewer list omitted CEO, design, and conformance | OpenSpec tasks now match README's complete reviewer matrix | Closed |
| R13 | MoA/Codex P2 | OpenSpec pseudo-code invented `effective_agent` | Corrected to the existing `recall(..., agent=agent)` parameter | Closed |
| R14 | MoA P3 | Research implications and default `get_memory` pre-fetch could expand scope | README/research classify the note as non-authorizing; default one-document in-process fetch is an explicit non-goal | Closed |
| R15 | Codex P1 | Restricted reports remained privacy-blocked governing inputs without hash closure | Direct current user instruction is recorded in `AUTHORIZATION-AND-PROVENANCE.md`; report hashes are historical provenance; exact content-free hashes freeze before code | Closed |
| R16 | Codex P1 | A corrupt pending marker could be overwritten by a later TUI session | Added atomic cross-session replacement refusal and a byte-identical/zero-sink end-to-end test contract | Closed |
| R17 | Self/Codex P1 | Two active full replacements of the recall requirement could overwrite ranking or authorization | Security delta is now a narrow ADDED requirement; overlapping relevance delta is policy-rebased and both validate strictly | Closed |
| R18 | Codex P2 | Body/secret scan had no executable scope or threshold | Added staged Gitleaks zero-leak gate, exact mutable-path allowlist, protected-path hard failure, and zero non-synthetic body threshold | Closed |
| R19 | Codex P2 | Normative authority was ambiguous and research appeared executable | README now classifies governing, subordinate, library, history, and receipt artifacts | Closed |
| R20 | Codex P3 | Systematic-review attribution/count was inaccurate | Corrected to Yang et al., 29 studies, and 25 distinct agents | Closed |
| R21 | Grok execution | First Grok run reached its turn limit before a verdict | A fresh bounded Grok review completed in round two; its findings are recorded below | Closed |
| R22 | Coordination | A concurrent stale-scope writer created/updated v2/unversioned and extra v3-named files | README authority table excludes them; staging is exact-path allowlisted; no production code was changed | Closed |
| R23 | Aristotle/Ada P1 | Report authority wording contradicted the historical-provenance boundary | Removed every governing-report claim; direct instruction plus approved content-free v3/OpenSpec are the only new authority | Closed |
| R24 | Aristotle/Ada P1 | Architecture overclaimed that every canonical body read occurs after authorization | Narrowed the diagram and contract to widened requests; retained default one-document prefetch is explicit | Closed |
| R25 | Aristotle P1 | Threat model claimed a non-human CLI distinction the code does not enforce | Scoped the threat to callers off `is_cli=True` and documented that v3 preserves, not authenticates, the CLI trust path | Closed |
| R26 | Aristotle/Ada P1 | Category staging language could admit stale concurrent-writer files; unstaged diff check was vacuous | Added literal per-repository manifests and required staged diff/name/secret gates | Closed |
| R27 | Aristotle P1 | Unqualified TUI sink invariant contradicted deliberate conflicting-session fail-closed behavior | Qualified the invariant to normal paths and stated the conflict-path change | Closed |
| R28 | Ada P2 | Stale-revision MCP test could still pass without reaching canonical validation | Required exact canonical error assertion plus proof that `fetch_document` ran | Closed |
| R29 | Ada P2 | Generated v3 HTML predated revised Markdown | Regenerated all three from current Markdown; byte-identical repeat render passed and will repeat after approval | Closed |
| R30 | Aristotle P1 | A staged final-delivery receipt could not contain the commit ID that contained it | Made the final handoff a post-commit user receipt outside both repositories and removed it from the manifest | Closed |
| R31 | Aristotle P1 | A broad OpenSpec hash freeze conflicted with task checkbox updates and archive relocation | Defined four governing hardening hashes plus a non-approving overlap integrity hash; excluded execution receipts and preserved hashes across archive | Closed |
| R32 | Ada P2 | Generated HTML referenced an untracked `spec.css` outside the exact manifest | Required standalone renders with no untracked local asset | Closed |
| R33 | Codex P1/Grok P3 | Changing ADR from Proposed to Accepted after review would create unreviewed governing bytes | Finalized the Accepted-candidate status before final conformance and prohibited post-review status edits | Closed |
| R34 | Grok P1 | Narrow ADDED requirements could archive beside ambiguous canonical parent permission text | Required policy-only canonical parent edits in the same commit and a zero Boolean-as-permission acceptance check | Closed |
| R35 | Grok P2 | Conflicting-session failure did not name an existing exception | Pinned body-free `RuntimeError`; no new type or TUI catch | Closed |
| R36 | Grok P2 | Stale-revision test asked for a nonexistent error `kind` | Pinned existing exit 10 plus generic canonical-state message and proof that fetch ran | Closed |
| R37 | Grok P2 | TUI logging language could imply an immutable app edit/test | Clarified that the existing generic catch is inspected and library fail-closed tests are sufficient | Closed |
| R38 | Grok P3 | Fernet token encoding needed an explicit bytes-to-ASCII boundary | Rule 2 already requires storing the returned token as ASCII; implementation must decode before JSON | Closed |
| R39 | Grok P3 | Ticket named `hook` but behavior matrix did not | Added the `hook` denial row and test requirement | Closed |
| R40 | Feynman P1 | Corrupt/wrong-key marker could neither complete nor satisfy rollback prerequisite | Made corruption a rollback stop; preserve bytes, retain v3, restore key or seek separate human incident authority | Closed |
| R41 | Feynman P2 | Encrypted marker schema, field types, and invalid UTF-8 were under-specified | Added exact persisted outer-field and decoded-digest types plus CryptoError tests for every decode/construction branch | Closed |
| R42 | Feynman P2 | Direct off-CLI denial was implicit | Added explicit `agent="codex", is_cli=False` before-index test | Closed |
| R43 | Feynman P2/P3 | Unrelated active relevance ranking text has a single-bucket cap tension and omits a normative tie key | Routed to `RELEVANCE-SPEC-001`; v3 freezes only hardening policy, does not approve or edit ranking clauses, and current code already uses ID tie-break | Closed for v3 scope |
| R44 | Ada P2 | `CryptoError` subclasses `RuntimeError`, so the conflict test could pass after wrong-key decryption | Required raw-session guard ordering, exact built-in exception type, and a forbidden-decrypt assertion | Closed |
| R45 | DevEx P2 | The three-HTML parity gate named no reproducible renderer or check command | Added exact Pandoc standalone render, byte-identical source-render comparison, and governed-output local-asset scan commands | Closed |
| R46 | DevEx P2 | Repeat rendering alone did not prove semantic parity, and the asset scan covered only stylesheets/scripts | Added an exact no-TOC source-render versus extracted-body comparison and a zero scan over resource-bearing HTML attributes and CSS URLs | Closed |
| R47 | Self P1 | A failing negative asset scan could be masked by a later command, and a raw CSS-URL search matched its own rendered command | Split CSS checks into actual style attributes/blocks, but the attempted `set -e` closure remained vacuous; see R49 | Superseded |
| R48 | Human authorization | R44-R47 made prior Codex/Grok verdicts stale after both reached the frozen invocation ceiling | User authorized v3.1: one fourth exact-byte invocation each and a 1,200,000-token ceiling; all other budgets, scope, evaluator, and gates remain unchanged | Closed |
| R49 | Codex P1 | Bash suppresses `errexit` for `! rg`, so a forbidden match or scan error could still be masked by the following command | Replaced inversion with an explicit conditional: match exits 1, no-match status 1 continues, and every `rg` error status propagates | Closed |
| R50 | Coordination P1 | A concurrent process modified protected Dr. Alex files in the review worktree after the frozen status check | Created `/Users/prax/Development/Hermes-Projects/dr-alex-memory-architecture-v1-clean` at exact baseline `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`; transferred exactly the nine allowlisted candidate Markdown/receipt paths byte-for-byte; no production or stale v2 file was copied | Closed |
| R51 | Human authorization | R49 and the failed Grok Build call exhausted v3.1 while the active user goal requires uninterrupted completion and states the specifications are pre-approved | Versioned only the review budget to v3.2: one fifth Codex/Grok review, one fourth MoA review, and 1,500,000 tokens; product scope, evaluator, cost cap, and stop rules are unchanged | Closed |
| R52 | Luna engineering/council P1 | The change spec ambiguously called the digest-only ciphertext an encrypted marker envelope | Pinned the persisted outer operational fields as plaintext, the token payload as digest-only, and aligned validation and corruption fixtures | Closed |
| R53 | Luna conformance/DevEx P1 | The agent-memory and staging commands were not fail-fast, and no executable exact-manifest comparison existed | Added `set -euo pipefail` and approved-spec-derived sorted staged-name comparisons for both repositories | Closed |
| R54 | Luna engineering P2 | Rollback cleanliness had no executable proof | Required the named recovery test to assert the injected temporary marker is absent after replay and made that assertion the rollback gate | Closed |
| R55 | Human authorization | A named review model or tool failure could still block uninterrupted completion | Required unavailable Codex, Grok, MoA, OpenCode, or other named-model lenses to be replaced by Codex Luna XHigh on the same exact bytes without weakening any gate | Closed |
| R56 | DevEx environment | The unqualified Dr. Alex full suite inherited global `commit.gpgsign=true`, so tests that create temporary repositories tried to unlock the user's SSH key | Re-ran the identical suite with `commit.gpgsign=false` injected only into the test-process environment; the suite passed and neither repository nor user Git configuration changed | Closed |

## Round-one decisions

- Architecture subagent: `FAIL / BLOCK`, core two-repair decision endorsed.
- Engineering subagent: `FAIL / BLOCK`, both root-cause code boundaries endorsed.
- MoA: `SPEC PASS / IMPLEMENTATION BLOCK` pending remaining reviewers.
- Codex: `FAIL / BLOCK` with the findings above.
- Grok: no verdict because the tool exhausted its turn limit.
- Design lens: N/A for current code because v3 authorizes no UI change; future PWA/TUI consent UX remains human-blocked.

## Current mechanical evidence

- `openspec validate harden-sensitive-request-authorization --strict`: PASS.
- `openspec validate improve-recall-relevance --strict`: PASS.
- Tracked `git diff --check` in both worktrees: PASS; untracked candidate files were reviewed
  directly, and the exact staged-name plus `git diff --cached --check` gate remains pending.
- Three current v3 HTML files: byte-identical repeat render PASS.
- Known external Codex review usage:
  `330,088 + 136,966 + 55,827 + 103,669 = 626,550` tokens. Grok and MoA did not
  expose token counts; Grok exhausted its four user-authorized calls, and MoA used all three.

## Round-two decisions

- Ada: `PASS` after exact-manifest and standalone-render closure.
- Aristotle: `PASS` after authority, trust-boundary, hash, and self-reference closure.
- Codex: `FAIL / BLOCK` on the pre-review ADR status transition; R33 is incorporated.
- Grok: `FAIL / BLOCK` on canonical archive ambiguity plus P2/P3 precision findings; R34-R39
  are incorporated.
- Feynman: `BLOCK` on rollback/validation/direct-test precision and inherited relevance findings;
  R40-R43 are incorporated or explicitly routed.
- Production files remain unchanged. Fresh narrow conformance verdicts are required.
- Production files: unchanged; implementation gate remains blocked.

## Round-three decisions

- Ada: `PASS` after R44's exact-type and forbidden-decrypt closure.
- CEO/product: `PASS`; the two-repair scope, non-goals, risk posture, and activation boundary are
  actionable and proportionate.
- Design/UX: `N/A-PASS`; v3 changes no UI and correctly leaves retention/consent UX human-blocked.
- Engineering: `PASS`; code boundaries, authorization ordering, rollback, and test contracts align.
- DevEx: `PASS` after R45-R47; the reproducible render, semantic-body, asset, and fail-fast
  checks passed exactly as documented.
- Codex: pre-R44 candidate received `FINAL SPEC PASS`; that verdict is stale because governing
  `CHANGE-SPEC-v3.md` changed at R44 and R45.
- Grok: the third invocation ended without a verdict; the named-reviewer invocation cap is reached.
- MoA: `FINAL SPEC PASS` on the current candidate; no P0-P3 findings.
- Production files remain unchanged; implementation remains blocked.

## Round-four decisions

- Codex: `BLOCK` on R49 and no other P0-P3 finding. Its two independent passes reproduced the
  shell-status defect and verified stable reviewed hashes.
- Grok: no verdict. The authorized fourth call failed before review with HTTP 402 because the
  Grok Build usage balance was exhausted.
- R49 is incorporated and locally proved for no-match, forbidden-match, and `rg`-error statuses.
  That edit makes every earlier exact-byte verdict stale.
- DevEx: `PASS` on the exact R49 closure; no P0-P3 findings.
- MoA: `FINAL SPEC PASS` on the post-R49 candidate; no P0-P3 findings.
- Coordination: protected Dr. Alex files outside this run's manifest changed concurrently; the
  intended `statefile.py`, `fanout.py`, and `test_fanout.py` paths remain unchanged.
- This run's intended production files remain unchanged. Fresh Codex and Grok exact-byte passes
  remain mandatory; implementation is blocked.

## Round-five decisions

- External Codex, direct Grok 4.6, and MoA each returned `FINAL SPEC PASS` on the pre-R52
  candidate; their verdicts became stale when R52-R55 changed governing bytes.
- Luna CEO and design lenses passed. Luna conformance, engineering, DevEx, and council blocked on
  R50 and R52-R54; every substantive finding is incorporated above.
- The active user completion goal supplies R55 model-substitution authority. A fresh Codex Luna
  XHigh review of the transferred exact bytes is required before the approval hash receipt.
- Clean-worktree transfer evidence closes R50. Production files remain unchanged; implementation
  remained blocked pending the renewed Luna exact-byte verdict and approval hash receipt.
- Codex Luna XHigh final role-lens review: `FINAL SPEC PASS`; CEO/product, architecture,
  security/privacy, engineering, testability, rollback, DevEx, conformance, and design N/A all
  passed with zero P0-P3 findings.
- Independent Codex Luna XHigh adversarial review: `FINAL SPEC PASS`; baselines, strict OpenSpec,
  HTML gates, 17/15-path manifest extraction, schema precision, and rollback proof all passed
  with zero P0-P3 findings.
- `SPEC-APPROVAL-v3.md` records the exact governing hashes. The implementation gate is open.

## Implementation and code-review decisions

- Dr. Alex tests-first receipt: the four new test groups produced 11 expected failures before
  code; after the minimal statefile/recovery edit, 25 focused fan-out/statefile tests passed.
- Dr. Alex changed-file Ruff format/lint and mypy passed; the full suite passed across 625
  collected tests with three expected skips, and `dr-alex --version` returned `0.1.0`.
- Global Dr. Alex Ruff lint passed. Global format still reports 36 unrelated baseline files and
  global mypy still reports the same 13 errors in six unrelated files; neither regressed.
- Agent-memory tests-first receipt: the new authorization cases produced 10 expected failures
  before code; the focused suite then passed 105 tests.
- Agent-memory full gate passed: 1,612 tests, three expected skips, one known warning; compile,
  43 planning-document pairs, and strict OpenSpec all passed.
- Codex Luna XHigh Dr. Alex code review: `CODE REVIEW PASS`, zero P0-P3 findings.
- Codex Luna XHigh agent-memory implementation and post-archive reviews: `FINAL CODE REVIEW
  PASS`, zero P0-P3 findings.
- The hardening archive contains exactly six files, retains all four approved hashes, leaves the
  active overlap hash unchanged, and validates with all 14 current OpenSpec items. Exact staging
  and secret gates remain before the two local commits.
