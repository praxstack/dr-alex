# Dr. Alex memory safety architecture v3

**Status:** Review candidate; implementation blocked  
**As of:** 2026-08-23  
**Activation:** Prohibited  
**Supersedes for implementation:** v2 rc3 candidate only; restricted historical reports remain immutable

## 1. Decision

This run will repair two verified security defects and will not build the proposed PWA
retention infrastructure:

1. Encrypt the existing TUI crash-recovery digest before it is persisted or replayed.
2. Make the legacy `include_sensitive` request use the existing high-sensitivity
   authorization rule in agent-memory recall and MCP full-body reads.

PWA durable fan-out remains blocked. Receiving or authenticating a message is not consent to
retain or promote it. No reviewed consent copy, retention duration, withdrawal/deletion
contract, sink policy, or reliable browser close protocol exists yet.

Existing TUI durable fan-out is also not declared consent-compliant by this review. v3 preserves
that legacy baseline to avoid silently disabling current product behavior, but preservation is
containment, not acceptance. `TUI-POLICY-001` records the required human disposition; no live
activation or migration is allowed while it remains unresolved.

This is the first rung that holds: it removes existing exposure without adding a database,
service, dependency, runtime, feature flag, sink, or dormant framework.

## 2. Restricted provenance and frozen repository baseline

Provenance and baselines:

| Input | SHA-256 or verdict |
|---|---|
| `therapist-stack-audit-2026-08-22.html` | `d349628361212722c06901b365dfc81d135fb4279e9655f9b5947d2a4c6e9005` |
| `dr-alex-memory-architecture-review-2026-08-23.html` | `1cc6e53eab0d1a7509f13d3aaf06db7c384d5d27fc382d3b47cf82a81372320c` |
| Research adversarial reverification | `PASS` |
| Dr. Alex baseline | `e0dad8a3f6e0e7016f74c6c3d53850c9a7892e7d` |
| agent-memory baseline | `a01bc4cb9697aaeff69671d82ea2dbca1f32cd38` |

The locally derived, content-free requirements retain conditional consolidation,
purpose-specific durable-retention consent,
confidentiality and erasure parity, and an isolated clinical memory boundary before migration.
They also require removal of the legacy high-sensitivity request bypass. This candidate changes
implementation only; it does not revise those gates or their evaluators.

## 3. Verified current architecture

| Area | Verified behavior | Consequence |
|---|---|---|
| Turn pipeline | TUI, one-shot, and PWA use `engine.run_turn`; RED triage short-circuits before retrieval and model | Safety path stays protected and out of scope |
| Transcript telemetry | Turn bodies are encrypted in `state.db`; current callers persist under legacy behavior | Existing behavior is not relabeled as consent-governed |
| TUI finalization | TUI calls `fanout.finalize_session` | Existing derived sinks remain unchanged |
| TUI recovery marker | `session_state.json` stores `UnfinalizedMarker.digest` as plaintext JSON | Existing at-rest privacy defect |
| PWA finalization | `/session/end` drains fragments, ends telemetry, and drops the in-memory session; it does not call fan-out | Lifecycle gap remains |
| Browser close path | The only normal `/session/end` call is tied to close-mood state; current JavaScript never enters that state | Hooking the endpoint would not make finalization unavoidable |
| PWA concurrency | Existing fan-out has one global recovery marker; PWA sessions may overlap | Existing fan-out cannot be reused safely without a broader design |
| agent-memory recall | `sensitivity_ceiling=high` is launch-identity gated; legacy `include_sensitive=true` bypasses that gate | General MCP and non-allowlisted direct callers off the CLI trust path can request high snippets |
| agent-memory full body | MCP `get_memory` treats `include_sensitive=true` as permission | General MCP clients can request a high-sensitivity body |
| Local filesystem | Current same-account files are not an OS isolation boundary | This run cannot claim physical clinical isolation |

No private conversation or clinical record was read to establish these facts.

## 4. Architecture boundary

```text
current turn
  -> deterministic triage
  -> RED: static crisis response, no retrieval/model
  -> GREEN/AMBER: existing retrieval, model, output gates
  -> existing encrypted telemetry behavior

existing TUI close
  -> distill once
  -> encrypted crash marker digest   [v3 repair]
  -> unchanged existing fan-out sinks

agent-memory request
  -> normalize requested sensitivity
  -> widened request: existing high-sensitivity authorization   [v3 repair]
  -> widened retrieval or widened canonical body fetch only when authorized

PWA durable close
  -> BLOCKED pending human-owned retention and lifecycle policy
```

Raw transcripts, derived memory, indexes, and prompt context remain separate record classes.
No rendered summary becomes transcript authority.

## 5. Decision A: protect the existing TUI marker

The crash marker contains a structured session digest with derived clinical text. File mode
`0600` and disk encryption are defense in depth, not application-layer encryption. The marker
must use the already-installed Dr. Alex Fernet helper and state key.

The runtime `UnfinalizedMarker.digest` remains a dictionary. Only its persisted representation
changes to `digest_enc`. A legacy plaintext marker remains readable so an interrupted session
can recover. Recovery rewrites it to ciphertext before any sink executes.

A valid ciphertext marker must be recovered before rollback. Wrong-key or corrupt ciphertext is
a stop condition, not a reason to discard the marker: preserve the bytes, retain v3, restore the
correct key if possible, and escalate a separate human incident decision if it remains
unrecoverable.

This decision adds no retained content and changes no normal, non-conflicting TUI sink,
consent, or safety behavior. The deliberate fail-closed change is that a new session cannot
replace a different still-pending marker or invoke a sink. Top-level `last_topic` remains
plaintext; v3 does not claim whole-file encryption.

## 6. Decision B: one authorization rule for high sensitivity

`include_sensitive` remains a compatibility spelling for requesting high scope. It no longer
grants that scope. Both it and `sensitivity_ceiling=high` use the existing
`authorize_ceiling("high", agent=..., is_cli=...)` rule before retrieval or MCP body fetch.

The existing CLI trust path (`is_cli=True`, intended for the human command entry point) and
accepted `dr-alex` identity-label behavior remain. V3 does not add a human/non-human distinction
inside that trusted CLI path. Low and medium access remains. A non-allowlisted or missing MCP
launch identity receives the existing loud ceiling refusal. Outside MCP, the explicit `agent`
argument remains a trusted same-user caller label; v3 does not turn that label into authenticated
process identity.

The repair covers widened `include_sensitive=true` body requests. The existing default
`get_memory` path may still resolve and read one canonical document in-process before its
current sensitivity refusal; changing that separate behavior is an explicit non-goal.

This is a policy hardening inside memctl. It is not authenticated process identity and not
filesystem isolation. Same-account processes can still read current files outside MCP; that
requires a later human-approved OS/service boundary.

## 7. Threat model

### Protected assets

- derived TUI session digests at rest;
- high-sensitivity recall snippets and canonical bodies exposed through MCP request tools;
- existing crisis and response-safety behavior;
- canonical memory and provenance history.

### In-scope attackers and failures

- a local reader that obtains `session_state.json` without the Keychain key;
- a model-controlled MCP request setting `include_sensitive=true`;
- a non-allowlisted direct caller off the trusted CLI path using the legacy flag;
- wrong-key or corrupt marker ciphertext;
- a crash while migrating and replaying a legacy marker.
- a later TUI session attempting to replace a still-pending marker it cannot recover.

### Out of scope and stated honestly

- a process running as the same macOS user reading plaintext memory files directly;
- Keychain compromise or an unlocked hostile host;
- clinical root/key/process isolation;
- retention consent, deletion, backup expiry, or restore-time erasure;
- Hermes or Telegram migration;
- therapeutic or clinical efficacy.

## 8. Staged program

### Stage 0: this run

- marker-digest encryption and safe legacy replay migration;
- request-flag authorization hardening;
- specs, OpenSpec delta, tickets, tests, reviews, and local commits;
- no live activation or data operation.

### Stage 1: human policy gates

Before PWA lifecycle implementation, a human-owned version must approve:

- exact consent copy, acquisition surface, subject, purpose, and proof;
- retention duration and default;
- withdrawal and deletion propagation across every sink, WAL, backup, and restore;
- allowed sinks, including whether Active File, inbox, agent-memory, continuity, or Notion are permitted;
- abandoned-tab, reload, timeout, retry, overlap, and restart semantics;
- RED retention and derived-output policy;
- rollback and activation authority.

The same human review must separately decide whether existing TUI fan-out is accepted under a
versioned policy, changed, or disabled. v3 makes none of those product decisions.

### Stage 2 and later

Only after Stage 1 may a new run design one replay-safe PWA lifecycle. Physical clinical
isolation and any Hermes consolidation remain separate later gates. Graph/vector work remains
deferred until a fixed held-out comparison proves material gain.

## 9. Rejected alternatives

| Alternative | Decision | Reason |
|---|---|---|
| v2 rc3 consent/lifecycle infrastructure | Reject for this run | Three tables, six flags, leases, 63 tests, and synthetic-only execution do not close the live lifecycle gap |
| Default-off PWA fan-out flag | Reject | A feature flag is not retention consent; enabled behavior reaches multiple sensitive sinks |
| Direct call to existing fan-out from `/session/end` | Reject | Browser close is not reliable, marker is global, risk/history state is incomplete, and consent is absent |
| New partial-frontmatter file reader | Reject | Existing canonical read is bounded, anchored, revision-checked, and single-read; authorization can occur at the existing boundary |
| New identity or policy framework | Reject | Existing high-ceiling helper is the correct shared control for this limited fix |
| New key for the marker | Reject | Existing state key and helper already cover Dr. Alex free text |

## 10. Acceptance and kill criteria

Accept only if:

- persisted crash markers contain ciphertext and no synthetic digest sentinel;
- a legacy plaintext marker is encrypted before its first replayed sink call;
- wrong-key ciphertext fails loudly and keeps the recovery marker visible;
- a different session cannot overwrite that pending marker or invoke a sink;
- `include_sensitive=true` is refused before recall/index access or MCP body fetch for an
  unapproved or missing MCP launch identity or a non-allowlisted direct caller label;
- authorized human CLI and `dr-alex`, plus low/medium behavior, remain green;
- Dr. Alex and agent-memory full test suites pass;
- protected safety files and runtime defaults do not change;
- every reviewer blocker and major finding is closed.

Reject or revert if any candidate adds a PWA sink, consent table, daemon, dependency, new key,
clinical data operation, safety-path change, plaintext digest, request-based grant, or physical
isolation claim.
