# Dr. Alex memory architecture change specification v5

**Status:** Review candidate; implementation blocked  
**Version:** `5.0.0-rc1`  
**Normative architecture:** `ARCHITECTURE.md`  
**Run contract:** `RUN-CONTRACT.md`  
**Activation:** Prohibited

## 1. Problem

The standalone PWA has authenticated turns and encrypted transcript telemetry, but no consent model, owner-bound sessions, or durable end-of-session receipt. The TUI has a reusable fan-out, but its crash marker is a single plaintext JSON payload. Agent-memory recall and full-body fetch let request `include_sensitive` authorize high-sensitivity content. The prior rc1 tried to solve these gaps and future clinical/Hermes stages in one run. Codex and Grok independently rejected it.

This version implements only changes that can improve code safely without creating a live clinical sink or changing runtime defaults.

## 2. Goals

1. Define one stable local subject and verified request actors.
2. Bind PWA sessions to the paired device that created them.
3. Persist default-deny consent receipts in existing `state.db` without coupling them to the telemetry kill-switch.
4. Make the shared transcript persistence seam consent-aware under an isolated, default-off enforcement profile.
5. Encrypt the legacy TUI marker digest and add encrypted per-session PWA finalization operations.
6. Extract one marker-free sink runner shared by the legacy TUI completion and synthetic PWA operation path.
7. Remove `include_sensitive` as authority for high-sensitivity recall snippets and full-body reads.
8. Preserve every existing safety invariant and durable-output default. Always-on PWA owner binding is the one intentional API hardening change.

## 3. Non-goals

This run does not:

- activate consent enforcement;
- change Room JavaScript to send consent grants;
- change current TUI memory behavior;
- create a clinical root, key, service user, daemon, socket, or live policy;
- claim physical clinical isolation;
- enable PWA writes to agent-memory, inbox, continuity, Active File, Notion, backup, or any new sink;
- edit Hermes source or therapist profile;
- build H1;
- migrate, read, decrypt, delete, or rewrite clinical data;
- build user-facing inspect, correct, forget, export, reset, or consent UI;
- change retrieval from current session-start behavior;
- add vector or graph retrieval;
- create a second transcript or event database;
- change crisis triage, RED short-circuit, output gates, corpus, or clinical policy.

## 4. Repository scope

No new live PWA sink is added. The Hermes finalize hook stays body-free and receives no transcript bodies.

### 4.1 Dr. Alex

Mutable code is limited to existing identity, pairing, state database, legacy state-file encryption, engine telemetry, PWA lifecycle, fan-out completion extraction, configuration documentation, and focused tests.

Protected Dr. Alex files and safety assets remain unchanged.

`D1-S02` compares these exact files to the v3 baseline before every candidate promotion:

| Protected path | SHA-256 |
|---|---|
| `persona/dr-alex.md` | `4e4077cbc72a0d6f83b01e01ad910cb350f0a6dc81593348edd3e4ac2de63204` |
| `dr_alex/improve.py` | `e2ece1da9d94cd97e50de1b1b1c7bc02f1447b3d85bbc85ec5d28357d283bc19` |
| `safety/triage.py` | `38a2069f9bb8327778b3b47247448f29a64bc26d2f85d161b32fe0f27d6c98b9` |
| `tests/golden_crisis/corpus.json` | `7f724974effc49e5e7a74e38247786b85e081bb241e7b995e6b4c8f8a7fcc6fe` |
| `tests/golden_crisis/test_golden_gate.py` | `e0260e27e32c426959228c4662923f902c27e69b620e51953a8ab26b199a0ed9` |
| `tests/test_improve.py` | `2b53cca5efe717489d30057bb7bab26fe724257f24c7fa362f9a36308d3e0b46` |

Any mismatch rejects the candidate before tests. Updating this manifest requires a new human-approved governing version; implementation does not edit it.

### 4.2 agent-memory

A separate clean worktree may change only MCP recall and full-body authorization logic, the existing sensitivity authorization helper, focused tests, and a privacy-safe OpenSpec note.

### 4.3 Hermes and Therapy Stack

Read-only. No source, profile, configuration, service, or runtime edit.

## 5. Domain model

### 5.1 Stable local subject

Add:

```text
local_subject_id() -> string
```

Rules:

- one subject for all local Dr. Alex surfaces in v5;
- derived from an existing Keychain-backed secret helper using HMAC-SHA256 over the fixed label `dr-alex-local-subject-v1`;
- expose only the first 16 digest bytes as URL-safe base64 with prefix `sub_`;
- deterministic for the same Keychain secret;
- never accepted from an API request;
- test keyring uses the existing in-memory backend.

### 5.2 Device principal

Add:

```text
DevicePrincipal:
    device_id: string
    actor_principal: string
```

`actor_principal` is `device:<device_id>`.

Replace token verification internals with:

```text
resolve_device_token(token, now, path) -> DevicePrincipal | null
```

The existing `verify_device_token` remains for compatibility and returns whether resolution succeeded.

Requirements:

- compare HMACs in constant time;
- return the matched non-revoked device ID;
- update last-used timestamp only after a match;
- never return or log the presented token;
- a database failure returns null.

### 5.3 Source

Enum:

```text
desktop
pwa
cli
```

TUI uses `desktop`. One-shot uses `cli`. alexd uses `pwa`.

### 5.4 Consent scope

Enum:

```text
transcript_retention
durable_memory
cross_surface_recall
clinical_export
clinical_share
```

D1 behavior exists only for the first two. The other scopes can be stored for forward compatibility but grant no behavior.

Unknown keys are rejected.

### 5.5 Consent decision

Enum:

```text
granted
denied
withdrawn
```

`withdrawn` stops later authorized work. This run does not delete already retained content and must not claim otherwise.

### 5.6 Consent receipt

Table `consent_receipts`:

| Column | SQLite type | Null | Rule |
|---|---|---:|---|
| `receipt_id` | TEXT | no | primary key, ULID |
| `subject_id` | TEXT | no | derived locally |
| `actor_principal` | TEXT | no | verified actor |
| `source` | TEXT | no | source enum |
| `scope` | TEXT | no | consent scope enum |
| `decision` | TEXT | no | decision enum |
| `effective_at` | TEXT | no | UTC ISO 8601 with `Z` |
| `expires_at` | TEXT | yes | UTC ISO 8601 later than effective time |
| `policy_version` | TEXT | no | default `3.0.0` |
| `copy_version` | TEXT | no | immutable copy ID |
| `retention_policy_version` | TEXT | no | immutable retention rule ID |
| `purpose_version` | TEXT | no | immutable purpose ID |
| `locale` | TEXT | no | BCP 47, test default `en` |
| `acquisition_channel` | TEXT | no | `api_test`, `desktop`, `pwa`, `cli` |
| `supersedes` | TEXT | yes | prior receipt ID |

Indexes:

- `(subject_id, source, scope, effective_at DESC, receipt_id DESC)`;
- unique receipt primary key;
- transactionally serialized replacement for one subject, source, and scope.

No body-bearing field is stored.

### 5.7 Effective consent

```text
EffectiveConsent:
    transcript_retention: bool = false
    durable_memory: bool = false
    cross_surface_recall: bool = false
    transcript_receipt_id: string | null = null
    durable_receipt_id: string | null = null
    cross_surface_receipt_id: string | null = null
    policy_version: string = "3.0.0"
```

Invariant:

```text
if transcript_retention is false:
    durable_memory = false
```

A durable grant without an active transcript grant is invalid and returns `durable_requires_transcript_retention`.

### 5.8 Session owner

Table `session_owners`:

| Column | SQLite type | Null | Rule |
|---|---|---:|---|
| `session_id` | TEXT | no | primary key |
| `subject_id` | TEXT | no | local subject |
| `actor_principal` | TEXT | no | verified device actor |
| `source` | TEXT | no | `pwa` in D1 |
| `created_at` | TEXT | no | UTC timestamp |
| `ended_at` | TEXT | yes | set once |

A session ID cannot be rebound to another actor.

### 5.9 Finalization operation

Table `finalization_operations`:

| Column | SQLite type | Null | Rule |
|---|---|---:|---|
| `operation_id` | TEXT | no | primary key, ULID |
| `session_id` | TEXT | no | unique |
| `subject_id` | TEXT | no | required |
| `source` | TEXT | no | source enum |
| `status` | TEXT | no | public lifecycle result or internal `running` |
| `payload_enc` | BLOB | yes | Fernet-encrypted retained digest and replay input |
| `step_state` | TEXT | no | body-free JSON map |
| `lease_owner` | TEXT | yes | opaque worker ID while resuming |
| `lease_generation` | INTEGER | no | starts at 1; increments on every successful claim |
| `lease_expires_at` | TEXT | yes | UTC timestamp, maximum 30 seconds |
| `created_at` | TEXT | no | UTC timestamp |
| `updated_at` | TEXT | no | UTC timestamp |
| `error_class` | TEXT | yes | class only |

`step_state` contains deterministic IDs and booleans only. It cannot contain snippets, summaries, topics, or conversation bodies.

## 6. Configuration

Add to the existing Dr. Alex configuration module and documentation:

| Key | Type | Default | Behavior |
|---|---|---:|---|
| `DR_ALEX_CONSENT_ENFORCEMENT` | boolean | `false` | enable consent resolution and transcript policy; does not gate ownership |
| `DR_ALEX_ALLOW_TEST_CONSENT` | boolean | `false` | accept `api_test` grants; tests only |
| `DR_ALEX_PWA_DURABLE_FINALIZATION` | boolean | `false` | allow operation runner; tests require synthetic sinks |
| `DR_ALEX_RECOVERY_TIMEOUT_SECONDS` | integer | `5` | range 1 to 30 |
| `DR_ALEX_MEMORY_POLICY_VERSION` | string | `3.0.0` | receipt evaluator version |

Unknown boolean values fail closed to `false`. Tests cover malformed values. TUI behavior is unchanged directly; it does not require a new feature flag.

No configuration flag controls session ownership. Owner binding is always on after D1.

No config enables a live sink automatically. `DR_ALEX_PWA_DURABLE_FINALIZATION=true` still requires an injected synthetic runner in tests. Production alexd has no live runner binding in this run.

## 7. Database migration

Increment the Dr. Alex schema version from its current value to the next integer. The migration:

1. opens existing `state.db` using the same path resolution;
2. creates the three new tables and indexes in one transaction;
3. changes no existing table or row;
4. records the new schema version only after successful creation;
5. rolls back fully on failure;
6. can run twice without error;
7. never depends on `telemetry_enabled()`.

`DR_ALEX_TELEMETRY_OFF` disables telemetry tables and transcript writes. It does not disable `consent_receipts`, `session_owners`, or `finalization_operations`. Those tables use an explicit policy-state connection path in the same database and never call `telemetry_enabled()`. Update the configuration documentation from “entire state.db store” to “telemetry and transcript data.”

A policy-table schema failure returns body-free `consent_store_unavailable`. Session ownership fails closed because it is authentication. It does not silently fall back to the unowned in-memory map.

## 8. Consent API

### 8.1 `POST /session/start`

Existing fields remain compatible. Optional test-only field:

```json
{
  "session_id": "optional-id",
  "mood": 1,
  "consent": {
    "transcript_retention": "granted",
    "durable_memory": "granted",
    "policy_version": "3.0.0",
    "copy_version": "test-copy-v1",
    "retention_policy_version": "test-retention-v1",
    "purpose_version": "test-purpose-v1",
    "locale": "en"
  }
}
```

Rules:

- when enforcement is disabled and `consent` is present, return HTTP 409 `consent_feature_disabled`;
- when enforcement is enabled but test consent is disabled, API grants return HTTP 403 `consent_channel_not_approved`;
- only isolated tests enable both settings;
- Room JavaScript keeps sending its current empty object;
- `subject_id`, actor, source, and acquisition channel are server-derived;
- unknown keys or scopes return HTTP 422 `unknown_consent_key`;
- invalid decisions return HTTP 422 `invalid_consent_decision`;
- durable grant without transcript grant returns HTTP 422 `durable_requires_transcript_retention`;
- missing consent creates no receipt and resolves durable scopes to deny under enforcement;
- denied or withdrawn input can supersede a test grant;
- malformed timestamps or policy identifiers return HTTP 422;
- the transaction writes all supplied scope decisions or none.

Response additions:

```json
{
  "session_id": "...",
  "consent_status": {
    "transcript_retention": "granted",
    "durable_memory": "granted",
    "cross_surface_recall": "denied"
  },
  "consent_active": true
}
```

When enforcement is disabled and no consent field is present, preserve the current response exactly except for backward-compatible optional fields.

### 8.2 Session ownership

Ownership is independent of consent enforcement and always active after D1.

- `require_device` returns a `DevicePrincipal`.
- `/session/start` is the only endpoint that creates a caller-supplied named session and owner row.
- `/turn` and `/session/end` require an existing owner row and never call `_get_or_create_session`.
- `/checkin` creates a server-generated owned session only when no session ID is supplied; a supplied ID must already belong to the actor.
- Start, turn, check-in, and end require an exact actor match.
- Unknown or other-device session IDs return HTTP 404 `session_not_found` without revealing owner identity.
- Global paired-device endpoints `/homework`, `/continuity`, and `/export/review` are outside this session-ownership slice.

## 9. Shared transcript persistence seam

Change the existing shared functions, not every caller:

```text
run_turn(..., transcript_policy: "legacy" | "retain" | "deny" = "legacy")
record_turn_telemetry(..., transcript_policy: "legacy" | "retain" | "deny" = "legacy")
```

Rules:

- `legacy` preserves current TUI, CLI, and default PWA behavior and is explicitly not consent-governed;
- the enforcement flag enrolls only alexd/PWA in this slice; TUI and one-shot CLI always pass `legacy` and are not silently enrolled;
- under PWA consent enforcement, alexd always passes `retain` or `deny`; absence defaults to `deny` before `run_turn`;
- the session stores the turn policy, but End re-resolves current consent before pending-fragment drain and replaces a stale cached `retain` with `deny` after expiry or withdrawal;
- safety trace remains body-free and may persist when telemetry is enabled;
- user and assistant transcript rows are skipped under `deny`;
- skipped bodies never reach encryption, SQLite, logs, or a recovery payload;
- telemetry-off disables telemetry and transcript writes; consent and ownership still work;
- a transcript write failure does not break the turn and logs exception class only.

This is the single transcript-retention enforcement point.

## 10. Lifecycle wrapper

Add one policy wrapper near existing fan-out code:

```text
finalize_authorized_session(
    session_id,
    subject_id,
    source,
    history,
    risk_tier_max,
    consent,
    runner = null,
    seams = synthetic_only,
    now
) -> LifecycleReceipt
```

The wrapper must not call existing live sinks by default.

### 10.1 Lifecycle enum

```text
closed_transient
finalized_no_memory_consent
finalized_red_withheld
finalization_disabled
finalization_unavailable
finalized
recovery_pending
session_not_found
```

`session_not_found` is a transport result and is never stored in `finalization_operations`.

### 10.2 Shared marker-free completion

Extract the sink-writing body of existing fan-out completion into:

```text
complete_digest(digest_input, seams, persist_step) -> FanoutResult
```

Rules:

- contains no call to `statefile.set_unfinalized`, `statefile.clear_unfinalized`, or another global marker function;
- legacy TUI `fanout.complete` calls `complete_digest` and maintains its encrypted legacy marker around it;
- the PWA operation runner calls `complete_digest` with synthetic seams and persists steps to its operation row;
- there is one sink-writing implementation, not a parallel fan-out;
- every synthetic sink ID is deterministic.

### 10.3 Algorithm

```text
function finalize_authorized_session(args):
    operation = load_operation(args.session_id)

    if operation exists:
        if operation.status is completed:
            return stored body-free receipt
        consent = resolve_current_consent(args.subject_id, args.source, now)
        if not consent.transcript_retention or not consent.durable_memory:
            if not compare_and_swap_claim(operation, worker_id, now):
                return recovery_pending
            fenced erase payload, stop unfinished steps, set finalized_no_memory_consent,
            clear lease, and return completed receipt
        if not compare_and_swap_claim(operation, worker_id, now):
            return recovery_pending
    else:
        consent = resolve_current_consent(args.subject_id, args.source, now)

    if operation does not exist and not consent.transcript_retention:
        atomically create a body-free completed operation:
            status = closed_transient
            payload_enc = null
            clear lease
        return completed receipt

    if operation does not exist and args.risk_tier_max == RED:
        atomically create a body-free completed operation:
            status = finalized_red_withheld
            payload_enc = null
            clear lease
        return completed receipt

    if operation does not exist and not consent.durable_memory:
        atomically create a body-free completed operation:
            status = finalized_no_memory_consent
            payload_enc = null
            clear lease
        return completed receipt

    if operation does not exist and not config.PWA_DURABLE_FINALIZATION:
        atomically create body-free completed operation:
            status = finalization_disabled
            payload_enc = null
            clear lease
        return completed receipt

    if operation does not exist:
        operation = create_or_load_authorized_operation(
            encrypted_payload,
            initial_status = running,
            initial_lease_owner = worker_id,
            lease_generation = 1,
            lease_expires_at = now + min(configured_timeout, 30 seconds)
        )
        if operation was loaded because another caller won the insert:
            if operation.status is completed:
                return stored body-free receipt
            consent = resolve_current_consent(args.subject_id, args.source, now)
            if not consent.transcript_retention or not consent.durable_memory:
                if not compare_and_swap_claim(operation, worker_id, now):
                    return recovery_pending
                fenced erase payload, stop unfinished steps, set finalized_no_memory_consent,
                clear lease, and return completed receipt
            if not compare_and_swap_claim(operation, worker_id, now):
                return recovery_pending

    if args.runner is null or seams are not synthetic:
        fenced update status finalization_unavailable, keep encrypted payload, clear lease
        return HTTP 503 receipt

    try:
        before each deterministic sink step:
            re-resolve current consent
            if retention or durable consent is absent, expired, or withdrawn:
                fenced erase payload, set finalized_no_memory_consent, clear lease, and stop
            renew lease for at most 30 seconds using owner and generation predicate
            abort stale worker if renewal updates zero rows
        complete_digest(operation payload, synthetic seams, fenced persist operation step)
        fenced update status finalized and clear lease
        return completed receipt
    catch named IO, crypto, scrub, or store error as error:
        fenced update status recovery_pending with error class and clear lease
        return HTTP 202 receipt
```

`create_or_load_authorized_operation` runs one transaction. The insert contains the encrypted payload, `running` status, owner, generation, and expiry before commit:

```text
INSERT INTO finalization_operations (...) VALUES (...)
ON CONFLICT(session_id) DO NOTHING;
SELECT ... WHERE session_id = ?;
```

For a loaded `recovery_pending`, `finalization_unavailable`, or expired `running` row, claim uses one compare-and-swap:

```text
UPDATE finalization_operations
SET status = running,
    lease_owner = worker_id,
    lease_generation = lease_generation + 1,
    lease_expires_at = now + lease_seconds
WHERE operation_id = operation_id
  AND status IN (recovery_pending, finalization_unavailable, running)
  AND (lease_expires_at IS NULL OR lease_expires_at <= now)
```

Exactly one caller can update one row. Every step, renewal, error, and completion update repeats the owner-and-generation predicate. Zero updated rows means the worker is stale and must stop without touching a sink.

Unexpected programming errors after operation creation set only the error class, release the lease, and re-raise. They do not return success.

### 10.4 Idempotency

- unique `session_id` creates at most one operation;
- concurrent same-session end requests converge on one row;
- deterministic memory and sink IDs derive from `subject_id + session_id + step + policy_version`;
- duplicate completed end returns the stored body-free receipt;
- duplicate pending or unavailable end re-resolves current consent, then resumes unfinished work under one fenced lease;
- two overlapping sessions have separate rows and payloads;
- policy-version changes do not replay completed sessions;
- start recovery and duplicate-end recovery call the same resume function;
- recovery runs only unfinished steps.

## 11. PWA lifecycle

### 11.1 Start and check-in

Ownership is always on:

1. authenticate and resolve device principal;
2. resolve local subject;
3. atomically create an owner row or load an active row for the same actor;
4. reject cross-device reuse and same-device reuse of an ended ID with external 404;
5. create the in-process session bound to the active owner.

Only `/session/start` creates a caller-supplied named session. `/checkin` with no session ID creates a server-generated owned session. `/checkin` with an ID requires that existing owner. `/turn` and `/session/end` never create missing sessions.

When consent enforcement is enabled in tests:

1. validate and store consent;
2. resolve effective consent, defaulting absent retention to deny;
3. store explicit `retain` or `deny` transcript policy on the session;
4. recover only same-subject unfinished operations after re-evaluating current consent;
5. do not assemble memory while recovery mutates a synthetic sink.

When consent enforcement is disabled, store `legacy` transcript policy and change no consent or durable-output behavior.

Recovery timeout:

- wait at most configured seconds;
- the worker may continue only under the operation resume lease;
- prompt assembly uses the last committed sink snapshot;
- timeout emits `recovery_degraded` with no body;
- no success claim until operation status is `finalized`.

### 11.2 Turn

- require an existing owner row and matching actor;
- never call `_get_or_create_session`;
- run existing shared turn;
- pass the session transcript policy explicitly;
- preserve RED short-circuit and output gates;
- do not add per-turn memory retrieval.

### 11.3 End

Ownership is always on. Consent and durable behavior depend on their separate flags.

1. require the owning actor; accept either a live session or an ended owner with an existing operation;
2. for a live enforced session, re-resolve consent before pending-fragment drain and derive current `retain` or `deny`;
3. only for that live session, drain with the current policy and close body-free telemetry;
4. when enforcement is disabled, drain with `legacy`, mark owner ended, remove session, preserve current durable-output behavior, and create no operation;
5. when enforcement is enabled, call the policy wrapper, which re-resolves consent again immediately before any resume claim;
6. remove the live session after a completed or durable pending record exists and mark owner ended once;
7. for retry after response loss, return or resume the existing operation without recreating the in-process session;
8. reject an ended owner with no operation using the same external 404;
9. return the persisted receipt.

Response:

```json
{
  "ok": false,
  "complete": false,
  "finalization": {
    "status": "recovery_pending",
    "operation_id": "...",
    "memory_written": false,
    "error_class": "StoreError"
  }
}
```

HTTP mapping:

| Status | HTTP | `ok` | `complete` |
|---|---:|---:|---:|
| completed lifecycle statuses | 200 | true | true |
| `finalization_unavailable` | 503 | false | false |
| `recovery_pending` | 202 | false | false |
| `session_not_found` | 404 | false | false |
| consent validation error | 422 | false | false |
| feature disabled with consent input | 409 | false | false |
| unapproved consent channel | 403 | false | false |

No response contains a body, summary, memory fact, device token, or subject ID.

## 12. TUI and CLI

### TUI

This run does not route TUI through the new policy wrapper or change its sink behavior. It changes only marker storage:

- `session_state.json` stores `digest_enc`, never plaintext `digest`;
- the existing Fernet helper encrypts canonical JSON bytes;
- load accepts a legacy plaintext digest for migration tests;
- the next successful save emits ciphertext only;
- decryption failure keeps recovery visibly pending and logs class only;
- existing `fanout.complete` calls the shared marker-free `complete_digest` and maintains its encrypted marker.

Focused tests prove the TUI call site and sink behavior remain green while persisted-file scans find no synthetic digest marker.

### One-shot CLI

This run does not add reusable-memory finalization. One-shot remains transient by default. Existing transcript telemetry behavior remains unchanged because consent enforcement is not activated for CLI.

## 13. RED contract

Under the new enforced PWA profile:

- retain encrypted transcript only with transcript-retention grant;
- write no reusable fact, inbox digest, continuity brief, Active File update, Notion export, or other derived content;
- lifecycle status is `finalized_red_withheld` when retained, otherwise `closed_transient`;
- current TUI behavior is unchanged because the profile is disabled there.

## 14. agent-memory request-flag hardening

### 14.1 Scope

Change MCP recall and full-body fetch so request `include_sensitive` is never authority.

### 14.2 Authorization

Reuse the current launch-agent sensitivity rule already used for explicit high ceiling. Do not add a writable policy file in this run.

Rules:

- low and medium recall and full-body reads keep current behavior;
- any request for high scope, whether `include_sensitive=true` or `sensitivity_ceiling=high`, requires the existing approved launch-agent rule;
- `include_sensitive` can remain accepted for compatibility but has no authorization effect by itself;
- request agent, client, root, project, tag, filter, or ceiling values never grant high access;
- recall authorizes before index retrieval;
- full-body fetch resolves the canonical path and opens it once with the existing no-follow rules;
- use unbuffered one-byte descriptor reads to find the opening and closing frontmatter delimiters, stopping exactly at the closing delimiter with no body read-ahead;
- cap frontmatter, including delimiters, at 65,536 bytes;
- missing or oversized frontmatter fails `metadata_unreadable` with no body read;
- authorize from parsed sensitivity;
- only after authorization, continue reading the remaining body from the same descriptor and enforce the existing canonical byte limit from `canonical.py`; do not introduce a second limit;
- unauthorized response includes only body-free authorization status;
- refusal logs include class and no query, snippet, slug body, or memory body;
- the existing authorized `dr-alex` launch behavior is covered by compatibility tests;
- the legacy general-client recall test is replaced by the frozen denial expectation;
- no new therapist high-sensitivity principal is added;
- no physical isolation claim is made.

### 14.3 Future boundary

A later contract must replace launch-name authorization with a non-self-asserted process identity and encrypted clinical service. This run must say that current same-user processes can still bypass MCP by direct filesystem access.

## 15. Errors and recovery

| Error | Behavior | Recovery |
|---|---|---|
| `consent_feature_disabled` | reject consent input | use current client behavior |
| `consent_channel_not_approved` | reject unapproved grant | human-reviewed activation later |
| `unknown_consent_key` | reject whole consent transaction | fix client |
| `invalid_consent_decision` | reject whole transaction | fix client |
| `durable_requires_transcript_retention` | reject whole transaction | grant retention or deny durable memory |
| `consent_store_unavailable` | deny consent behavior and session creation | operator repairs DB; never fall back to unowned session |
| `session_not_found` | reveal no owner | create or use owned session |
| `session_owner_mismatch` | return same external 404 | use owning device |
| `crypto_failed` | write no payload | durable operation remains pending if created |
| `finalization_unavailable` | HTTP 503, no sink write | bind synthetic runner in tests only |
| `metadata_unreadable` | deny high full-body request before body read | repair canonical frontmatter |
| `recovery_pending` | HTTP 202 incomplete | retry unfinished deterministic steps |
| `authorization_denied` | no high body or snippet | use approved launch path |
| unexpected programming error | propagate to transport handler; class-only log | fix code; do not mark success |

Retries are bounded by request lifetime. No blind loop runs inside the request.

## 16. Observability

Body-free fields only:

- source;
- lifecycle status;
- consent decision counts by scope, excluding subject and actor;
- transcript-retention skipped count;
- operation pending count and oldest age;
- duplicate end count;
- owner mismatch count;
- authorization denial count;
- duration and error class.

Never log subject ID, actor ID, device token, receipt body, transcript, summary, memory body, or key material.

## 17. Test matrix

All fixtures use synthetic neutral text and throwaway databases, roots, keys, and sinks.

### 17.1 Identity and ownership

| ID | Case | Expected |
|---|---|---|
| D1-I01 | valid device token | matched device principal returned |
| D1-I02 | revoked or unknown token | null and 401 |
| D1-I03 | request supplies subject-like field | rejected or ignored; server value wins |
| D1-I04 | other device turns, checks in to, or ends session | external 404 |
| D1-I05 | local subject repeated | stable value |
| D1-I06 | `/turn` with missing session | 404; no implicit creation |
| D1-I07 | `/checkin` without session ID | server-generated owned session |
| D1-I08 | `/checkin` with other-device session | external 404 |

### 17.2 Schema and consent

| ID | Case | Expected |
|---|---|---|
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

### 17.3 Transcript persistence

| ID | Case | Expected |
|---|---|---|
| D1-T01 | retention granted | encrypted user and assistant rows |
| D1-T02 | retention denied | no transcript rows; safety trace remains if enabled |
| D1-T03 | existing caller omits new argument | baseline behavior unchanged |
| D1-T04 | transcript failure | turn returns; class-only warning |
| D1-T05 | RED plus retention denied | no body row and no derived sink |
| D1-T06 | RED plus retention granted | encrypted body row, no derived sink |
| D1-T07 | pending fragment drained at end under deny | zero transcript rows for fragment and reply |

### 17.4 Finalization operations

| ID | Case | Expected |
|---|---|---|
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

### 17.5 Compatibility and safety

| ID | Case | Expected |
|---|---|---|
| D1-S01 | full baseline suite | exit 0; same skips allowed |
| D1-S02 | immutable safety hashes | unchanged |
| D1-S03 | TUI source diff | no behavioral call-site change |
| D1-S04 | one-shot source diff | no durable-memory addition |
| D1-S05 | default config PWA | no new durable sink or operation |

### 17.6 agent-memory

| ID | Case | Expected |
|---|---|---|
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

### 17.7 RC4 candidate regressions

These are additive candidate tests. They do not edit or replace the 63 frozen outcomes in `EVALUATOR-v3.md`.

| ID | Case | Expected |
|---|---|---|
| RC4-R01 | retention expires after turn but before End | End re-resolves before drain; pending fragment and reply write no body |
| RC4-R02 | durable consent withdrawn before resume | claimant erases replay payload and runs no unfinished sink step |
| RC4-R03 | no retention, no durable, RED, and writer-disabled terminal branches | `payload_enc`, `lease_owner`, and `lease_expires_at` are null in every body-free terminal row |
| RC4-R04 | two first End requests race | one insert owns generation 1; loser returns pending and calls no sink |
| RC4-R05 | lease expires during recovery | one takeover increments generation; stale worker writes zero steps and no final status |
| RC4-R06 | same device starts an ended session ID | external 404; no in-process session is recreated |
| RC4-R07 | duplicate End after response loss | same owner receives existing receipt or resumes it without a live session |
| RC4-R08 | default configuration End | no `finalization_operations` row and existing durable-output behavior is unchanged |

The live `memctl doctor` exit 7 remains a disclosed operational blocker. This run does not call M1 physical isolation ready.

## 18. Verification commands

Dr. Alex focused tests, then:

```bash
uv run pytest -q
```

Agent-memory focused tests, then:

```bash
uv run --project tools/memctl pytest -q
```

Before every commit:

```bash
git diff --check
git status --short
git diff --staged
```

Before candidate promotion, recompute the six `D1-S02` hashes from section 4.1 and compare them byte-for-byte. The implementation and test diff budget is measured against each repository baseline named in `RUN-CONTRACT.md`; governing, review, receipt, and generated HTML files are excluded. The cap is 1,500 net changed implementation/test lines per repository.

Run a secret/body marker scan over the diff and generated review documents. Do not scan or print live clinical data.

## 19. Ticket DAG

Implementation uses six planned commits under the frozen maximum of eight:

| Ticket | Repository | Blocked by | Deliverable |
|---|---|---|---|
| D1-A | Dr. Alex | v5 exact-hash independent PASS | subject, device principal, schema, consent resolver |
| D1-B | Dr. Alex | D1-A | owner-bound sessions and consent-aware transcript seam |
| D1-C | Dr. Alex | D1-B | encrypted per-session operations and synthetic-only wrapper |
| M1-A | agent-memory | v5 exact-hash independent PASS | request flag no longer grants high recall snippets or full-body reads |
| V1-D1 | Dr. Alex | D1-C | full D1 conformance and code-review repair |
| V1-M1 | agent-memory | M1-A | full M1 conformance and code-review repair |

D1-A and M1-A may proceed in parallel only in separate worktrees. A commit touches one repository. Six planned implementation commits fit the frozen eight-commit ceiling. The two contingency slots may be used only for review-proven material defects in the same authorized slices. Budget is not permission to add work.

Later human-gated tickets are documented but not published as ready-for-agent:

- M1-B physical encrypted clinical service;
- H1 body-free finalize adapter plus committed-session reader;
- user inspect, correct, forget, export, and reset operations;
- backup/restore erasure proof;
- cross-surface activation and canary.

## 20. Definition of done for this run

### Documents

- v5 architecture, change spec, governing evidence, evaluator, and run contract are internally consistent;
- Codex, Grok, plan, council, and fresh-context conformance findings are reconciled;
- independent final verifier returns PASS;
- HTML is regenerated as a derived local rendering only after the accepted Markdown hashes are frozen; HTML is not an approval input.

### D1

- consent and owner tables migrate safely;
- request actor owns every PWA session;
- enforcement profile defaults deny and Room JS sends no grant;
- shared seam suppresses transcript rows under deny;
- new operation payloads are encrypted and per-session;
- no default PWA durable sink is added;
- TUI, CLI, and safety behavior stay unchanged by default;
- focused and full suites pass.

### M1-A

- request `include_sensitive` cannot authorize high-sensitivity recall snippets or a high full-body read;
- existing approved Dr. Alex compatibility remains tested;
- no clinical root, key, service, or new therapist grant is created;
- focused and full suites pass.

### Completion statement

The final report must say:

- this run improves consent, ownership, persistence, operation recovery, and request-flag authorization;
- physical clinical isolation, deletion productization, and Hermes integration remain incomplete;
- `memctl doctor` remains unresolved unless a later verified candidate fixes it without touching live data;
- no live configuration, clinical data, Telegram route, gateway, or activation changed.
