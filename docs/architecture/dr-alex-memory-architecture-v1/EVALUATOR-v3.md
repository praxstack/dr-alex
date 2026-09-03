# Dr. Alex Memory Architecture v3 Frozen Evaluator

**Status:** Frozen for the v3 implementation run  
**Fixtures:** Synthetic content only  
**Candidate cannot edit this file or its thresholds**

## Baseline gates

- Dr. Alex full suite SHALL pass with no protected safety regression relative to `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d`.
- agent-memory full suite SHALL pass with no regression relative to `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38`.
- `memctl doctor` exit 7 is a carried baseline defect and cannot be reported as fixed without a separate measured repair.
- Dr. Alex crisis corpus, RED short-circuit, frozen sections, deterministic output gates, encryption-at-rest, and loopback controls SHALL remain unchanged.
- No test may contain private clinical text.

## Candidate acceptance threshold

A candidate passes only when all 63 named outcomes below pass, both full suites pass, protected controls do not regress, the diff stays within the run budget, and independent standards plus spec review report no blocker or major defect. A candidate that changes this evaluator, its expected outcomes, or its thresholds is rejected.

## Frozen synthetic outcomes

| ID | Scenario | Required outcome |
|---|---|---|
| D1-I01 | valid device token | matched device principal returned |
| D1-I02 | revoked or unknown token | null and 401 |
| D1-I03 | request supplies subject-like field | rejected or ignored; server value wins |
| D1-I04 | other device turns, checks in to, or ends session | external 404 |
| D1-I05 | local subject repeated | stable value |
| D1-I06 | `/turn` with missing session | 404; no implicit creation |
| D1-I07 | `/checkin` without session ID | server-generated owned session |
| D1-I08 | `/checkin` with other-device session | external 404 |
| D1-C01 | migrate existing v1 DB | rows preserved; new tables exist |
| D1-C02 | migration rerun | no-op success |
| D1-C03 | unknown key | HTTP 422 |
| D1-C04 | malformed decision | HTTP 422 |
| D1-C05 | durable without retention | HTTP 422 |
| D1-C06 | absent consent under enforcement | all durable scopes deny |
| D1-C07 | grant then withdraw | later resolver denies |
| D1-C08 | equal timestamp | higher ULID deterministically wins |
| D1-C09 | malformed stored timestamp | scope denied; body-free diagnostic |
| D1-C10 | telemetry off | consent still resolves |
| D1-C11 | enforcement off plus consent input | HTTP 409 |
| D1-C12 | unapproved consent channel | HTTP 403 |
| D1-C13 | Room JS source scan | no `granted` consent payload |
| D1-C14 | latest grant expired | scope resolves deny |
| D1-C15 | telemetry off | owner and consent tables still write through policy-state connection |
| D1-T01 | retention granted | encrypted user and assistant rows |
| D1-T02 | retention denied | no transcript rows; safety trace remains if enabled |
| D1-T03 | existing caller omits new argument | baseline behavior unchanged |
| D1-T04 | transcript failure | turn returns; class-only warning |
| D1-T05 | RED plus retention denied | no body row and no derived sink |
| D1-T06 | RED plus retention granted | encrypted body row, no derived sink |
| D1-T07 | pending fragment drained at end under deny | zero transcript rows for fragment and reply |
| D1-F01 | no retention | `closed_transient`, no encrypted payload |
| D1-F02 | retention, no durable | `finalized_no_memory_consent` |
| D1-F03 | RED retained | `finalized_red_withheld`, no sink |
| D1-F04 | durable grant, writer disabled | `finalization_disabled`, no sink |
| D1-F05 | synthetic writer enabled | marker-free `complete_digest` runs through synthetic sinks |
| D1-F06 | partial synthetic failure | encrypted operation stays `recovery_pending` |
| D1-F07 | duplicate end after response loss | same operation and receipt |
| D1-F08 | overlapping sessions | separate rows; no overwrite |
| D1-F09 | persisted-file scan | no synthetic body or digest plaintext |
| D1-F10 | consent withdrawn before replay | unfinished derived steps stop |
| D1-F11 | policy version changes | completed session not re-extracted |
| D1-F12 | pending response | HTTP 202, `ok=false`, `complete=false` |
| D1-F13 | concurrent end on same session | one row; one lease; both responses reference same operation |
| D1-F14 | pending duplicate end | one caller resumes unfinished steps; no duplicate sink |
| D1-F15 | writer enabled without runner | `finalization_unavailable`, HTTP 503 |
| D1-F16 | legacy plaintext TUI marker fixture | load succeeds; next save contains `digest_enc` only |
| D1-F17 | TUI marker decryption failure | recovery stays visibly pending; class-only log |
| D1-S01 | full baseline suite | exit 0; same skips allowed |
| D1-S02 | immutable safety hashes | unchanged |
| D1-S03 | TUI source diff | no behavioral call-site change |
| D1-S04 | one-shot source diff | no durable-memory addition |
| D1-S05 | default config PWA | no new durable sink or operation |
| M1-A01 | general launch plus high recall plus `include_sensitive=true` | authorization denied before retrieval |
| M1-A02 | general launch plus high full body plus `include_sensitive=true` | authorization denied before body return |
| M1-A03 | approved existing launch plus high recall and body | current authorized behavior preserved |
| M1-A04 | low and medium recall and bodies | current behavior preserved |
| M1-A05 | crafted request agent, root, tag, filter, ceiling, or flag | cannot grant high scope |
| M1-A06 | refusal log scan | no query, snippet, or body marker |
| M1-A07 | legacy general-client opt-in test | replaced by frozen v2 denial expectation before code |
| M1-A08 | full updated suite | baseline count adjusted only for the deliberate security expectation; all unrelated tests pass |
| M1-A09 | high full-body denial | body bytes after frontmatter delimiter are never read |
| M1-A10 | oversized or missing frontmatter delimiter | `metadata_unreadable`, no body return |
| M1-A11 | file changed during authorization | same descriptor prevents path-swap disclosure |

## Stop rule

- Reject after two consecutive candidates without held-out improvement.
- Stop at the first run-budget limit.
- Do not change a test outcome, threshold, or protected control to obtain PASS.
