# Dr. Alex memory architecture v5

**Status:** Review candidate; implementation blocked  
**As of:** 2026-08-23  
**Supersedes:** `ARCHITECTURE.md` rc1 in Git history  
**Run contract:** `RUN-CONTRACT.md`  
**Activation:** Prohibited

## 1. Purpose

Dr. Alex needs one consent-governed memory lifecycle across its standalone surfaces and, later, Hermes. Remembering everything does not mean putting all history in every prompt. It means processing every authorized event through a traceable policy, keeping raw records separate from derived memory, and retrieving only the minimum authorized context for the current task.

Dr. Alex is not a clinician, diagnostic system, or emergency service. Current-turn safety logic remains independent of memory.

## 2. Current verified state

| Component | Current state | Evidence class |
|---|---|---|
| Dr. Alex TUI | Calls the existing fan-out at session end | source and tests |
| Dr. Alex PWA | Ends telemetry and drops in-memory session; no fan-out | source and tests |
| Dr. Alex one-shot CLI | Flushes Hermes-independent session telemetry; no reusable-memory finalization contract | source |
| Dr. Alex transcripts | Encrypted in `state.db`, but every turn persists regardless of retention consent | source |
| Dr. Alex crash marker | One global plaintext JSON payload that can hold a derived digest | source |
| PWA identity | Device token validates, but current helper discards the matched device ID | source |
| agent-memory MCP | Available to the therapist profile as a manual tool path | live config and logs |
| agent-memory full-body read | High sensitivity can be enabled by request `include_sensitive` | source |
| agent-memory recall | Explicit `sensitivity_ceiling=high` is launch-name gated, but legacy request `include_sensitive=true` still returns high snippets to a general MCP client | source and tests |
| agent-memory storage | Markdown canonical store; no content-encryption adapter | source |
| Hermes finalize hook | Emits session ID, platform, and reason, not transcript bodies | source |
| Universal continuity | Not proven | absence of end-to-end receipt set |

The earlier report wording that agent-memory was not connected is stale. It is registered and manually callable. Automatic lifecycle capture remains unproven.

## 3. Architecture decisions

### A1. Canonical and derived records stay separate

The architecture recognizes these record classes:

1. consent receipts;
2. authorized encrypted transcript events;
3. encrypted finalization operations and step receipts;
4. structured reusable memories;
5. summaries and continuity artifacts;
6. rebuildable indexes;
7. prompt context selected for one turn.

No summary, index, or prompt fragment becomes the canonical transcript.

### A2. Receipt is not consent

Message receipt proves transport. It does not grant retention, reusable memory, cross-surface recall, or export.

### A3. One subject, distinct actors and sources

Dr. Alex is a local single-user system for this version.

- `subject_id` identifies the one local user. It is an opaque stable value derived locally and never accepted from a request.
- `actor_principal` identifies who supplied a decision or request. PWA uses the verified paired-device ID. TUI and local CLI use fixed local actors while the process remains single-user.
- `source` identifies the interaction surface: `desktop`, `pwa`, or `cli`.
- A PWA session is owned by one paired-device actor. Another device cannot turn, check in to, end, or reopen that session.

Homework, continuity, and date-range export are global paired-device endpoints today. They are outside the session-ownership slice and remain gated only by existing device authentication.

Cross-surface recall uses the common subject and distinct source labels, but remains disabled until its own grant and later integration tests pass.

### A4. Authenticated local requests imply transient processing

The system may process an authenticated local request to answer the current turn. D1 does not persist a separate `transient_processing` grant. Durable scopes remain default deny.

### A5. Durable memory requires retained provenance in the enforced profile

When `DR_ALEX_CONSENT_ENFORCEMENT=true` for the alexd/PWA profile:

```text
durable_memory_granted implies transcript_retention_granted
```

Under that profile, absent transcript retention writes body-free safety telemetry only. It writes no transcript body, summary, reusable memory, inbox note, continuity brief, Active File update, Notion export, or finalization payload.

When PWA enforcement is false, legacy transcript behavior remains unchanged and is explicitly not called consent-governed. TUI and one-shot CLI remain on explicit `legacy` policy in this slice even if an operator sets the alexd/PWA flag; they are not silently enrolled. Human activation must decide how to migrate them. This rule avoids inventing a second provenance store.

### A6. Ownership ships independently; TUI memory behavior stays unchanged

PWA owner binding is an authentication hardening change and is always on after D1. Only `/session/start` creates a named session. `/turn` and `/session/end` require an existing owner. `/checkin` creates a session when no ID is supplied and otherwise requires the existing owner. Cross-device mismatch returns external 404.

Consent enforcement and PWA durable finalization remain default off. Existing TUI memory behavior remains unchanged in this slice; no compatibility flag is needed.

The activation gate must decide how to migrate or replace legacy TUI consent behavior. Code must not silently turn it off or treat it as consent.

### A7. Current-turn safety precedes retrieval and persistence

The current turn follows this order:

```text
authenticate request
    -> resolve subject, actor, source, and effective consent
    -> deterministic safety triage
    -> RED: crisis response, no retrieval, no derived memory
    -> GREEN or AMBER: current session-start memory behavior
    -> model and output gates
    -> body-free telemetry
    -> transcript policy: enforced profile retains only with active consent; legacy profile preserves current behavior
```

RED behavior for the new consent-enforced path is explicit:

- no book or memory retrieval;
- no reusable memory, inbox, continuity, Active File, or Notion write;
- encrypted transcript retention only when an active transcript-retention grant permits it;
- current legacy TUI behavior remains unchanged while consent enforcement is disabled.

### A8. Encrypted state for legacy and new finalization

D1 encrypts the existing TUI marker digest in `session_state.json` with the existing Dr. Alex Fernet helper. Metadata stays plaintext. Loading a legacy plaintext marker is supported in tests and the next successful state write replaces it with ciphertext. The user-facing TUI fan-out behavior does not change.

Only the consent-enforced PWA path stores a `finalization_operation` in existing `state.db`; default configuration creates no such row. Body-bearing fields are encrypted. A denied-retention, denied-durable, RED, or writer-disabled terminal row is body-free, has no replay payload, and stores null lease owner and expiry. Authorized writer-enabled durable work atomically creates or loads one row and claims one fenced lease. Duplicate end requests return its completed receipt, resume unfinished steps under a current-consent check, or report that another worker owns the lease. Two sessions cannot overwrite each other.

Extract the sink-writing body from existing fan-out completion into one marker-free shared function. Legacy TUI `complete` calls it and maintains its encrypted marker. The PWA operation runner calls it with synthetic sinks and its operation row, never the global marker. D1 enables no new live PWA writer.

### A9. Request fields never grant high-sensitivity access

`include_sensitive`, requested client names, tags, roots, filters, and sensitivity ceilings can narrow a request. They cannot grant authority.

Removing request-flag authority is safe to implement now. Physical clinical isolation is not.

### A10. Physical clinical isolation is a later approved stage

The existing general root and same-user processes cannot satisfy physical clinical isolation. POSIX modes are defense-in-depth, not the boundary.

The later M1 physical-isolation stage requires a separately approved design with:

- a non-self-asserted process identity;
- an encrypted clinical store;
- a key unavailable to the general Hermes process;
- an authenticated local transport;
- explicit key ownership, rotation, restore, and failure behavior;
- synthetic proof that the general identity cannot read a clinical fixture;
- no fallback to general storage.

No clinical root, key, user, daemon, socket, or live policy is created in this run.

### A11. Hermes integration uses a body-free finalize hook

H1 remains a later stage. The finalize hook stays body-free.

The current hook carries session metadata only. A later H1 adapter must:

1. receive session ID, source, and reason;
2. authorize the adapter and resolve consent;
3. read an already committed session through a narrow profile-aware session-store API;
4. create an encrypted, idempotent local job;
5. return within the existing finalize timeout;
6. ship disabled.

The hook payload never gains transcript bodies for this architecture.

### A12. Retrieval remains session-start BM25 in this run

No per-turn retrieval rewrite, vector dependency, graph projection, or new selector belongs in D1 or request-flag hardening. Current session-start memory assembly remains the implemented behavior. Later retrieval changes require held-out gain with no safety or privacy regression.

## 4. Consent model

### 4.1 Scopes

| Scope | Meaning | D1 status |
|---|---|---|
| `transcript_retention` | keep encrypted conversation bodies after the turn | implemented disabled |
| `durable_memory` | extract reusable memory from retained authorized events | implemented disabled; depends on retention |
| `cross_surface_recall` | recall authorized memory on another source | receipt only; behavior disabled |
| `clinical_export` | send or export clinical content outside the canonical local store | not implemented |
| `clinical_share` | share selected content with an approved person or system | not implemented |

Absent, expired, malformed, denied, or withdrawn consent resolves to deny.

### 4.2 Consent receipt

A receipt contains:

| Field | Type | Rule |
|---|---|---|
| `receipt_id` | ULID string | primary key |
| `subject_id` | opaque string | derived locally |
| `actor_principal` | opaque string | verified actor |
| `source` | enum | `desktop`, `pwa`, `cli` |
| `scope` | enum | one known scope |
| `decision` | enum | `granted`, `denied`, `withdrawn` |
| `effective_at` | UTC timestamp | required |
| `expires_at` | UTC timestamp or null | later than effective time |
| `policy_version` | semantic version string | policy evaluator version |
| `copy_version` | string | immutable displayed-copy ID |
| `retention_policy_version` | string | immutable retention rule ID |
| `purpose_version` | string | immutable purpose statement ID |
| `locale` | BCP 47 string | default `en` in tests |
| `acquisition_channel` | enum | `api_test`, `desktop`, `pwa`, `cli` |
| `supersedes` | ULID string or null | prior decision for subject, source, scope |

No conversation body belongs in a receipt.

The Room JavaScript cannot send `granted` before consent copy and UI receive design and human approval. D1 may exercise grants only through synthetic tests or operator fixtures in an isolated profile.

### 4.3 Resolution

Resolution is one transactionally ordered query by subject, source, scope, `effective_at`, then `receipt_id`. It accepts rows only when `effective_at <= now` and `expires_at` is null or later than `now`. It rejects malformed rows and unknown keys. Equal timestamps are ordered by higher ULID first. A malformed active row denies the scope and emits a body-free diagnostic.

## 5. D1 storage contract

D1 adds tables to existing encrypted Dr. Alex state infrastructure. Consent itself is not controlled by `DR_ALEX_TELEMETRY_OFF`. If consent storage is unavailable, durable processing fails closed.

### 5.1 `consent_receipts`

Stores the fields in section 4.2. Schema migration increments the existing schema version and upgrades an existing database without dropping rows.

### 5.2 `session_owners`

| Field | Type | Rule |
|---|---|---|
| `session_id` | string | primary key |
| `subject_id` | opaque string | required |
| `actor_principal` | opaque string | verified paired device for PWA |
| `source` | enum | required |
| `created_at` | UTC timestamp | required |
| `ended_at` | UTC timestamp or null | set once |

### 5.3 `finalization_operations`

| Field | Type | Rule |
|---|---|---|
| `operation_id` | ULID string | primary key |
| `session_id` | string | unique |
| `subject_id` | opaque string | required |
| `source` | enum | required |
| `status` | enum | section 6 |
| `payload_enc` | bytes or null | encrypted retained digest and replay input |
| `step_state` | JSON text | body-free deterministic step IDs and statuses |
| `lease_owner` | string or null | opaque resume worker ID |
| `lease_generation` | integer | starts at 1 and increments on each successful claim |
| `lease_expires_at` | UTC timestamp or null | maximum 30 seconds |
| `created_at` | UTC timestamp | required |
| `updated_at` | UTC timestamp | required |
| `error_class` | string or null | exception class only |

No free text is plaintext. Operation creation is atomic and unique by session. Authorized durable creation commits encrypted replay payload, status `running`, owner, generation, and lease expiry in one transaction. A duplicate request reads the existing operation. Every step/final update is fenced by `(operation_id, lease_owner, lease_generation)`; a stale worker whose lease was replaced cannot mutate state.

## 6. Lifecycle status contract

One public result enum is used in architecture, API, tests, and receipts. An operation may use internal status `running` while it owns a lease; `running` is never returned as a lifecycle result:

- `closed_transient`: no retained transcript and no durable memory;
- `finalized_no_memory_consent`: transcript retained, durable memory denied;
- `finalization_disabled`: consent permits durable memory but the default-off writer gate prevents any sink call;
- `finalized_red_withheld`: transcript may be retained, all derived outputs withheld;
- `finalized`: authorized operation completed;
- `finalization_unavailable`: writer enabled but no approved runner is bound;
- `recovery_pending`: accepted operation is incomplete and has a durable retry record;
- `session_not_found`: unknown session and no prior operation.

API rules:

- completed states return HTTP 200 with `ok: true`, `complete: true`;
- `finalization_unavailable` returns HTTP 503 with `ok: false`, `complete: false`;
- `recovery_pending` returns HTTP 202 with `ok: false`, `complete: false`;
- `session_not_found` returns HTTP 404 with `ok: false`, `complete: false`;
- no response contains a transcript or memory body.

## 7. D1 lifecycle

### Start

1. authenticate device and resolve the verified device actor;
2. resolve stable local subject;
3. atomically create the owner row, or load an active row for the same actor;
4. reject an existing session owned by another actor with external 404;
5. reject reuse of an ended session ID with the same external 404; ended IDs are never reopened;
6. when consent enforcement is enabled, validate test-only consent input, persist receipts, and resolve effective consent;
7. when consent enforcement is enabled, recover only same-subject operations authorized by consent re-resolved immediately before lease claim;
8. assemble current session-start memory only when current behavior and gates permit it;
9. create the in-process session bound to the owner row.

Only `/session/start` creates a caller-supplied named session. `/checkin` may create a server-generated session when no ID is supplied; with an ID it requires the existing owner. `/turn` and `/session/end` never create a missing session.

A timed-out recovery job cannot continue mutating shared state without its durable operation row. Prompt assembly never reads from a sink that an unfinished worker is changing.

### Turn

1. require the same actor that owns an existing session;
2. run the shared safety-first turn;
3. always write body-free safety telemetry when telemetry is enabled;
4. under consent enforcement, pass explicit `retain` or `deny` transcript policy, defaulting absent consent to `deny`;
5. under legacy mode, pass explicit `legacy` policy and preserve current transcript behavior;
6. for a live session, re-resolve current consent at End and apply that current policy to pending-fragment drain.

### End

1. require the owning actor; an active session follows the normal end path, while an ended owner may access only its existing operation receipt or resume path;
2. when consent enforcement is active and the session is live, re-resolve current consent **before** pending-fragment drain, derive `retain` or `deny`, and drain with that current policy;
3. when enforcement is disabled and the session is live, drain with `legacy`, close telemetry, mark the owner ended, remove the live session, and create no operation;
4. under enforcement, short-circuit absent/expired/withdrawn retention, RED, and denied durable memory into body-free completed operation receipts with `payload_enc = null`;
5. for authorized durable work, create the operation with encrypted payload and an initial fenced lease, or load the existing row;
6. return completed receipts unchanged;
7. before every loaded pending/unavailable/running-expired resume, re-resolve current consent without mutating the operation;
8. claim resumable work with one compare-and-swap over status and lease expiry;
9. if the resolved consent is absent, expired, or withdrawn, erase the payload under the active fence, store the body-free no-memory result, and stop all unfinished work;
10. before each sink step, re-resolve current consent, then renew the lease; withdrawal or expiry erases the payload under the active fence and stops all unfinished work;
11. fence every step and final write by lease owner and generation;
12. return HTTP 202 when another unexpired worker owns the lease; a stale worker cannot write after takeover;
13. remove the in-process session only after a completed or durable pending record exists, mark the owner ended once, and return the persisted result.

An End retry after response loss may succeed without a live session only when the same actor owns an ended session and a matching operation exists. It returns or resumes that operation; it never recreates the in-process session. An ended owner with no operation returns the same external 404.

No broad `except Exception` converts programmer errors into success. Named operational storage, crypto, and scrub failures produce `recovery_pending` if an operation exists. Unexpected errors log class only and propagate to the transport error handler.

## 8. Current sink inventory

Every later retention, withdrawal, deletion, backup, and export design must account for:

| Sink | Current content class | D1 rule |
|---|---|---|
| `statedb.transcripts` | encrypted raw bodies | consent-aware when enforcement enabled |
| `session_state.json` legacy marker | encrypted derived digest plus body-free metadata | encryption migration; existing TUI behavior preserved |
| finalization operation | encrypted retained digest and body-free step receipts | new, per-session |
| agent-memory canonical facts | plaintext Markdown today | no new PWA write |
| agent-memory inbox | derived digest | no new PWA write |
| continuity brief | derived summary | no new PWA write |
| Active File | derived clinical text | no new PWA write |
| Notion mirror | third-party export | always off without `clinical_export` |
| Dr. Alex backups | encrypted database bundles and files | no policy change in D1 |
| derived index | rebuildable search data | no new D1 index |

A later deletion manifest must list every sink, status, attempt, and receipt. It remains pending until canonical, derived, backup/restore, and export policies are satisfied. D1 does not claim the user-control product is complete.

## 9. M1 request-flag hardening

Safe current-run change:

- keep `include_sensitive` accepted for one compatibility version if needed;
- treat it only as a request for high scope, never as authority;
- apply the existing launch-agent authorization rule before high-sensitivity recall snippets and before high-sensitivity full-body fetch;
- for recall, authorize before index retrieval;
- for full-body fetch, resolve the canonical path, open it once without following symlinks, parse bounded frontmatter from that descriptor, authorize, then read the remaining body from the same descriptor;
- deny unauthorized high-sensitivity recall and full-body reads with body-free status;
- prevent request fields from granting roots or high scope;
- include the existing authorized `dr-alex` launch behavior in compatibility tests;
- replace the legacy test that allowed a general client to use `include_sensitive=true` with the frozen v2 denial test;
- create no clinical root and grant no new therapist access.

This change is not physical clinical isolation and must not be described as such.

## 10. Threat model

### Assets

- retained transcript bodies;
- reusable memories;
- finalization payloads;
- consent receipts;
- encryption keys;
- launch-identity authorization rules;
- deletion and backup receipts.

### Boundaries

- browser to loopback PWA;
- paired device to owned session;
- Dr. Alex process to state database;
- Dr. Alex to agent-memory CLI/MCP;
- general process to future clinical service;
- local store to Notion or export target;
- canonical store to backups and indexes.

### Required abuse tests

- spoofed subject or session owner;
- grant input from unapproved Room JavaScript;
- misspelled scope;
- expired, withdrawn, or malformed consent;
- durable grant without retention;
- telemetry disabled while consent is required;
- duplicate and overlapping end requests;
- plaintext marker search;
- launch-identity spoof plus crafted `include_sensitive` or high ceiling;
- unauthorized same-path knowledge;
- Notion export without export consent;
- RED session with every sink inspected;
- lost response followed by duplicate end;
- restore that contains a deleted synthetic ID.

## 11. Program stages

1. **v5 document repair.** Architecture, change spec, threat model, tickets, independent PASS.
2. **D1 disabled consent and lifecycle infrastructure.** No new live PWA durable writer.
3. **M1 request-flag hardening.** No clinical root or new grant.
4. **Human design gate.** Consent copy, retention, clinical service identity, encrypted root, deletion, backup, and rollback.
5. **M1 physical isolation in a new approved run.** Synthetic evidence before live provisioning.
6. **H1 disabled Hermes adapter in a new approved run.** Body-free hook plus authorized committed-session reader.
7. **Offline cross-surface parity.** Synthetic data only.
8. **Human activation gate.** Live changes only if every earlier gate passes.

## 12. Kill criteria

Reject or revert a candidate if:

- a protected safety file changes;
- raw content appears in logs or review artifacts;
- consent absence becomes a durable grant;
- transcript bodies persist under enforced deny;
- Room JavaScript sends an unreviewed grant;
- a device accesses another device-owned session;
- a marker or operation payload is plaintext;
- duplicate or overlapping finalization loses or duplicates work;
- request input grants high-sensitivity access;
- a new PWA write reaches an existing live sink;
- the candidate claims physical isolation without the later gate;
- the evaluator or threshold changes with candidate code;
- two consecutive candidates show no held-out gain;
- a frozen budget is exceeded.

## 13. Architecture acceptance

This architecture passes review only when an independent verifier confirms:

- one subject, actor, source, consent, and status contract;
- no rc1 sequencing contradiction;
- transcript retention controls the shared persistence seam;
- durable memory depends on retained provenance;
- per-session encrypted operations replace the plaintext global marker for new behavior;
- current TUI and live PWA behavior do not change by default;
- M1 is described as request-flag hardening only in this run;
- physical clinical isolation and H1 remain later human-gated stages;
- every current sink is named;
- the ticket graph fits the frozen budget;
- no protected safety or clinical content changed.
