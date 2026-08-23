# Dr. Alex memory safety v3 change specification

**Status:** Review candidate; implementation blocked  
**Normative architecture:** `ARCHITECTURE-v3.md`  
**Candidate repositories:** Dr. Alex and agent-memory  
**New dependencies:** none

## 1. Scope

Two independent security tickets are ready after specification approval:

- `DA-SEC-001`: encrypt and safely migrate the existing TUI crash-marker digest;
- `AM-SEC-001`: route the legacy high-sensitivity request through existing authorization.

PWA lifecycle implementation is not ready and is specified only as a blocked decision ticket.

## 2. Protected invariants

The implementation must not change:

- triage-first ordering, RED short-circuit, crisis content, or golden RED recall;
- the single `llm.complete` entry point or deterministic output gates;
- normal, non-conflicting TUI fan-out eligibility, digest content, sink order, or sink behavior;
- default PWA, one-shot, Hermes, Telegram, Notion, backup, or live-service behavior;
- agent-memory canonical Markdown/Git authority, single writer, provenance, supersession,
  quarantine, archive, index rebuildability, or default low/medium recall;
- live clinical data, credentials, configuration, services, or profiles.

## 3. DA-SEC-001: encrypted crash-marker digest

### 3.1 Root cause

`statefile.set_unfinalized` serializes `asdict(UnfinalizedMarker)`, including `digest`, directly
into `data/session_state.json`. The digest may contain insights, open threads, homework, and
durable learnings. The file is private by mode but its body is plaintext.

### 3.2 Files

- `dr_alex/statefile.py`
- `dr_alex/fanout.py`
- `tests/test_fanout.py`

No other Dr. Alex source or test file is required.

### 3.3 Persisted representation

The in-memory dataclass does not change. On disk, an active marker has:

```json
{
  "unfinalized": {
    "session_id": "synthetic-id",
    "started_at": "2026-08-23T00:00:00Z",
    "end_ts": "2026-08-23T00:01:00Z",
    "inbox_filename": "deterministic.md",
    "digest_enc": "<Fernet token>",
    "remembered": [],
    "inbox_written": false,
    "continuity_written": false
  }
}
```

The operational marker fields surrounding `digest_enc` remain plaintext. Only the JSON object
carried by `digest` is encrypted into the token; there is no encrypted outer marker envelope.

Normative rules:

1. `set_unfinalized` removes plaintext `digest` from the persisted payload.
2. It serializes the digest using deterministic JSON (`sort_keys=True` and compact
   separators), encrypts those bytes with existing `dr_alex.crypto` and
   `STATE_KEY_ACCOUNT`, and stores the ASCII Fernet token as `digest_enc`.
3. It performs encryption before the atomic state-file update. Encryption failure changes no
   marker and calls no sink.
4. `SessionState.marker()` validates the persisted outer marker object before construction. Its
   exact fields are the seven plaintext operational fields shown above plus the `digest_enc`
   string: `session_id`, `started_at`, `end_ts`, and `inbox_filename` are strings; `remembered` is
   a list of non-Boolean integers; and `inbox_written` and `continuity_written` are Booleans. It
   then decrypts `digest_enc` through existing `crypto.decrypt`, decodes UTF-8, parses JSON, and
   requires the decoded digest to be an object before constructing the unchanged runtime marker.
5. If `digest_enc` exists, a wrong key, invalid UTF-8, malformed JSON, a non-object decoded
   digest, or missing, extra, or wrongly typed persisted outer fields raises `crypto.CryptoError`;
   it must not fall back to any plaintext `digest` field.
6. A legacy marker with `digest` and no `digest_enc` remains readable.
7. `recover_if_needed` persists the decoded marker through `set_unfinalized` before calling
   `complete`. This migrates legacy plaintext before the first replayed sink or step receipt.
8. Existing body-free TUI recovery logging already catches generic exceptions. No TUI edit or
   new catch is required. The serialized `unfinalized` object remains, so the existing raw-marker
   staleness signal remains active; library tests assert the fail-closed behavior.
9. Top-level state metadata is unchanged and may remain plaintext.
10. The inaccurate `statefile.py` module text that calls this file metadata-only/non-clinical is
    corrected; it must describe the encrypted derived digest and remaining plaintext metadata.
11. The atomic `set_unfinalized` update refuses to replace a nonempty marker whose raw
    `session_id` differs from the new marker. Same-session progress updates remain allowed. A
    conflicting session reads the raw `session_id` and raises the exact built-in `RuntimeError`
    with a body-free message before `marker()`, decryption, file change, or sink invocation, so a
    corrupt or wrong-key pending marker cannot be erased by the next TUI finalization. Do not add
    an exception type or TUI catch.

### 3.4 Test

`test_recovery_encrypts_legacy_marker_before_first_sink` uses a legacy marker containing a
unique synthetic digest sentinel. The first injected sink asserts that the raw file:

- contains `digest_enc`;
- does not contain the sentinel or a plaintext `digest` member;
- still round-trips to the same runtime digest;
- completes normal replay once, with existing idempotency behavior;
- finally asserts `statefile.load(sp).marker() is None` on the injected temporary state path.

`test_encrypted_marker_corruption_fails_loudly` is parameterized over a valid token encrypted
with a different synthetic key, valid ciphertext containing invalid UTF-8, malformed JSON, and a
non-object JSON value, plus persisted encrypted-marker records with missing, extra, or wrongly
typed plaintext outer fields. The decrypted payload fixtures contain only the digest value. The
wrong-key case also supplies a valid legacy plaintext digest and proves ciphertext is
authoritative: every case raises `crypto.CryptoError`, preserves the raw marker, calls no sink,
and never falls back to plaintext.

`test_marker_encryption_failure_preserves_existing_marker` injects an encryption failure before
`set_unfinalized` updates the file and proves the exact prior bytes remain and no sink runs.

`test_conflicting_session_cannot_replace_pending_marker` leaves a synthetic wrong-key marker for
session A, installs a forbidden-decrypt spy, attempts finalization for session B with injected
seams, and proves `exc_info.type is RuntimeError`, a body-free message, zero decrypt calls,
byte-identical session-A state, and zero sink calls. The exact-type and no-decrypt assertions
prevent `crypto.CryptoError` (a `RuntimeError` subclass) from satisfying the test vacuously. Do not
add a new fixture framework.

### 3.5 Rollback

Revert the Dr. Alex commit only after proving no marker is pending. A valid ciphertext marker must
be completed with v3 first. A wrong-key or corrupt marker prohibits rollback: preserve exact
bytes, retain v3, restore the correct key if possible, and require separate human incident
authority if it remains unrecoverable. Verification must prove no pending synthetic marker
remains in the test worktree. The final temporary-path assertion in
`test_recovery_encrypts_legacy_marker_before_first_sink` is the executable rollback proof. It
does not inspect repository state or any live marker, and no live marker is read or migrated
during this run.

## 4. AM-SEC-001: authorize the legacy sensitive request

### 4.1 Root cause

`include_sensitive=true` widens `RecallPolicy.allowed_sensitivities` to high, while
`recall.recall` authorizes only `sensitivity_ceiling`. MCP `get_memory` separately treats the
same Boolean as permission. The request is model-controlled and the existing tests codify the
bypass for a general client.

### 4.2 Governing policy change

The current user's direct hardening instruction and the content-free v3 architecture require
removal of the legacy bypass. The agent-memory OpenSpec change must update `derived-index` and
`mcp-transport` before code is accepted. The old accepted-risk exception remains preserved in
Git history; after approval, v3 is the new versioned policy. Restricted reports remain historical
provenance rather than implementation authority.

Archive acceptance is stricter than adding a second requirement beside stale text. In the same
atomic commit, canonical `derived-index` must update the parent sensitivity paragraph so
`include_sensitive=true` requests, but never grants, authorized high scope. Canonical
`mcp-transport` must replace “explicit opt-in” permission wording with an authorized high-scope
request and apply the launch-identity rule to the legacy flag. Neither canonical file may retain
a sentence that makes the Boolean sufficient permission. The unrelated ranking clauses in the
active `improve-recall-relevance` change are not approved or changed by v3.

### 4.3 Files

Production:

- `tools/memctl/memctl/recall.py`
- `tools/memctl/memctl/mcp.py`

Tests and specification:

- existing affected tests under `tests/test_mcp.py`, `tests/test_recall.py`,
  `tests/test_index.py`, and `tests/test_index_trust.py`;
- one OpenSpec change, the resulting canonical `derived-index` and `mcp-transport` deltas, and a
  policy-only rebase of the overlapping active `improve-recall-relevance` derived-index delta.

Do not change `fetch_document`, `fetch_slug`, canonical path resolution, filesystem layout, or
client policy storage.

### 4.4 Recall contract

Before opening an index or resolving candidates:

```python
requested_ceiling = "high" if opts.include_sensitive else opts.sensitivity_ceiling
authorize_ceiling(requested_ceiling, agent=agent, is_cli=is_cli)
```

Keep existing type validation and the rule that callers cannot specify both legacy and new
high-scope controls. In MCP, request-body `agent`, project, tag, root, and filter values remain
filters only; only `self.client` supplies the launch identity. Direct Python/CLI callers retain
the existing accepted same-user trust in the explicit `agent` label. This patch does not claim
that either label is an OS principal.

### 4.5 MCP full-body contract

In `_tool_get_memory`, before calling `fetch_document`:

```python
if include_sensitive:
    recall_mod.authorize_ceiling(
        "high", agent=self.client or "unknown", is_cli=False
    )
```

Retain the existing single canonical resolution, sensitivity check, revision check, and bounded
read. Preserve the wire field shape and body-free `isError=true` refusal shape. Update both MCP
tool descriptions to say that `include_sensitive=true` requests high scope and still requires an
authorized launch identity; the Boolean is not permission.

### 4.6 Behavior matrix

| Caller | Request | Result |
|---|---|---|
| Human CLI | legacy high or explicit high | unchanged, authorized |
| `dr-alex` launch client | legacy high or explicit high | unchanged, authorized |
| Non-allowlisted MCP launch client | default low/medium | unchanged |
| Non-allowlisted MCP launch client | `include_sensitive=true` | loud ceiling refusal before read |
| Non-allowlisted MCP launch client | explicit high ceiling | existing loud ceiling refusal |
| `hook` launch client | `include_sensitive=true` | loud ceiling refusal before read |
| Missing MCP launch client | `include_sensitive=true` | loud ceiling refusal before read |
| MCP request-body `agent=dr-alex` | legacy or explicit high | denied unless launch client is authorized |
| Direct caller label `agent=dr-alex` | legacy or explicit high | unchanged, authorized under existing same-user trust |
| Direct caller label `agent=codex`, `is_cli=False` | `include_sensitive=true` | loud ceiling refusal before index read |

Raw local `fetch_document`, `fetch_slug`, and the human CLI slug path remain trusted APIs. This
patch does not pretend a launch label is an OS security principal.

### 4.7 Tests

Tests must prove:

1. general, `hook`, missing, and spoofed launch clients cannot use `include_sensitive` for recall;
2. a direct `agent="codex", is_cli=False` request and unauthorized MCP requests refuse before
   `index.open_readonly`;
3. general and missing launch clients cannot use it for MCP `get_memory`;
4. refusal occurs before `fetch_document`;
5. spoofed request fields do not grant high scope;
6. authorized human CLI and `dr-alex` retain current behavior;
7. low and medium behavior remains unchanged;
8. direct tests that intentionally exercise high data declare `is_cli=True` or an authorized
   launch agent instead of relying on the removed exception;
9. the stale-revision `get_memory` test runs its widened leg as authorized `dr-alex`, proves
   `fetch_document` was reached, and pins the existing `exit=10` plus
   `slug '<slug>' is not available from current canonical state` payload; it must not add a new
   `kind` field or pass vacuously at the pre-fetch gate;
10. the full suite passes with synthetic stores only.

Use existing helpers and fixtures. No new test framework or private content is permitted.

### 4.8 Rollback

Revert the single agent-memory commit containing code, tests, canonical spec updates, and the
archived OpenSpec change. Rollback restores the legacy accepted risk; it does not alter memory
files, indexes, services, or live data.

## 5. PWA-POLICY-001: blocked decision ticket

No PWA lifecycle code may start until a human-owned policy version defines every Stage 1 item in
`ARCHITECTURE-v3.md`. The eventual implementation must first repair the browser lifecycle and
prove abandoned-tab/restart handling; merely calling existing fan-out from `/session/end` is not
acceptable.

This ticket is not ready for an agent, must not be published with a ready label, and has no code
acceptance claim in this run.

## 5A. TUI-POLICY-001: blocked legacy-retention decision

Existing TUI fan-out is preserved as baseline behavior but is not certified as consent-compliant.
A human must explicitly accept it under a versioned purpose/retention/deletion/sink policy,
change it, or disable it. This is a blocked policy ticket, not implementation authority.

## 6. Verification

### Dr. Alex

```bash
set -euo pipefail

uv run pytest -q tests/test_fanout.py::test_recovery_encrypts_legacy_marker_before_first_sink
uv run pytest -q tests/test_fanout.py tests/test_statefile.py
uv run ruff format --check dr_alex/statefile.py dr_alex/fanout.py tests/test_fanout.py
uv run ruff check dr_alex/statefile.py dr_alex/fanout.py tests/test_fanout.py
uv run mypy dr_alex/statefile.py dr_alex/fanout.py
uv run pytest -q
uv run dr-alex --version

DOC_DIR=docs/architecture/dr-alex-memory-architecture-v1
for stem in RUN-CONTRACT-v3 ARCHITECTURE-v3 CHANGE-SPEC-v3; do
  pandoc --standalone --toc "$DOC_DIR/$stem.md" --output "$DOC_DIR/$stem.html"
done
for stem in RUN-CONTRACT-v3 ARCHITECTURE-v3 CHANGE-SPEC-v3; do
  cmp -s "$DOC_DIR/$stem.html" <(pandoc --standalone --toc "$DOC_DIR/$stem.md")
  diff -u <(pandoc --to=html "$DOC_DIR/$stem.md") \
    <(sed -n '/<\/nav>/,/<\/body>/p' "$DOC_DIR/$stem.html" | sed '1d;$d')
  if rg -n '(?i)(<(link|script|img|source|video|audio|iframe|embed|input|track|use)[^>]+(href|src|srcset|poster)=|<object[^>]+data=|<[^>]+style=[^>]*url\()' \
    "$DOC_DIR/$stem.html"; then
    exit 1
  else
    asset_scan_status=$?
    [ "$asset_scan_status" -eq 1 ] || exit "$asset_scan_status"
  fi
  awk '/<style>/{in_style=1} in_style && /url\(/{exit 1} /<\/style>/{in_style=0}' \
    "$DOC_DIR/$stem.html"
done
```

### agent-memory

```bash
set -euo pipefail

openspec validate harden-sensitive-request-authorization --strict
openspec validate improve-recall-relevance --strict

UV_NO_SYNC=1 PYTHONDONTWRITEBYTECODE=1 \
uv run --project tools/memctl --frozen pytest -p no:cacheprovider -q \
  tests/test_mcp.py tests/test_recall.py \
  tests/test_index.py::test_t6_rebuild_equivalence_idsets_and_dump \
  tests/test_index_trust.py::test_current_revision_still_reauthorizes_canonical_sensitivity_policy

UV_NO_SYNC=1 PYTHONDONTWRITEBYTECODE=1 \
uv run --project tools/memctl --frozen pytest -p no:cacheprovider -q

UV_NO_SYNC=1 PYTHONDONTWRITEBYTECODE=1 \
uv run --project tools/memctl --frozen python -m compileall -q tools/memctl/memctl

UV_NO_SYNC=1 PYTHONDONTWRITEBYTECODE=1 \
uv run --project tools/memctl --frozen python tools/docs/render_planning.py check

openspec validate --all --strict
```

After adding only the exact manifest below to the index, run for both repositories:

```bash
set -euo pipefail

git diff --cached --check
git status --short
git diff --staged
gitleaks git --staged --redact --no-banner
```

The exact Dr. Alex staged manifest is:

```text
docs/adr/0001-memory-retention-gate.md
docs/architecture/dr-alex-memory-architecture-v1/ARCHITECTURE-v3.html
docs/architecture/dr-alex-memory-architecture-v1/ARCHITECTURE-v3.md
docs/architecture/dr-alex-memory-architecture-v1/CHANGE-SPEC-v3.html
docs/architecture/dr-alex-memory-architecture-v1/CHANGE-SPEC-v3.md
docs/architecture/dr-alex-memory-architecture-v1/README.md
docs/architecture/dr-alex-memory-architecture-v1/RESEARCH-EVIDENCE.md
docs/architecture/dr-alex-memory-architecture-v1/RUN-CONTRACT-v3.html
docs/architecture/dr-alex-memory-architecture-v1/RUN-CONTRACT-v3.md
docs/architecture/dr-alex-memory-architecture-v1/TICKETS-v3.md
docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/AUTHORIZATION-AND-PROVENANCE.md
docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/CODE-REVIEW-v3.md
docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/REVIEW-LEDGER-v3.md
docs/architecture/dr-alex-memory-architecture-v1/reviews/v3/SPEC-APPROVAL-v3.md
dr_alex/fanout.py
dr_alex/statefile.py
tests/test_fanout.py
```

The exact agent-memory staged manifest is the following, with the six change files located only
at the archive path after archive (the pre-archive path must then be absent):

```text
openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/.openspec.yaml
openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/design.md
openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/proposal.md
openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/specs/derived-index/spec.md
openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/specs/mcp-transport/spec.md
openspec/changes/archive/2026-08-23-harden-sensitive-request-authorization/tasks.md
openspec/changes/improve-recall-relevance/specs/derived-index/spec.md
openspec/specs/derived-index/spec.md
openspec/specs/mcp-transport/spec.md
tests/test_index.py
tests/test_index_trust.py
tests/test_mcp.py
tests/test_recall.py
tools/memctl/memctl/mcp.py
tools/memctl/memctl/recall.py
```

`git diff --cached --name-only` must equal the applicable sorted manifest exactly; missing and
extra paths both fail. The Gitleaks threshold is zero verified staged leaks. Any `data/`,
`memories/`, `private/`, `events/`, `inbox/`, unrelated `archive/`, `quarantine/`, `snapshots/`,
credential, configuration, or service path is a hard failure. Independent diff review must find
zero non-synthetic personal names, conversation excerpts, or clinical record bodies. No command
reads the live memory corpus or a live clinical database. The documented Pandoc commands must
regenerate the three v3 HTML files as standalone documents from the approved Markdown. The
byte-for-byte repeat render, exact heading/body fragment comparison, and zero resource-bearing
HTML element, inline-style URL, or style-block URL checks must pass before staging.

Run the applicable executable manifest comparison from each repository after staging. Both
commands read the approved specification from the clean Dr. Alex worktree and fail if the
heading is absent, the extracted manifest is empty, or any staged path differs.

Dr. Alex:

```bash
set -euo pipefail
APPROVED_SPEC=/Users/prax/Development/Hermes-Projects/dr-alex-memory-architecture-v1-clean/docs/architecture/dr-alex-memory-architecture-v1/CHANGE-SPEC-v3.md
expected_manifest="$(awk -v heading='The exact Dr. Alex staged manifest is:' '
  $0 == heading { wanted=1; next }
  wanted && $0 == "```text" { block=1; next }
  block && $0 == "```" { exit }
  block { print }
  END { if (!block) exit 2 }
' "$APPROVED_SPEC")"
test -n "$expected_manifest"
diff -u \
  <(printf '%s\n' "$expected_manifest" | LC_ALL=C sort) \
  <(git diff --cached --name-only | LC_ALL=C sort)
```

agent-memory:

```bash
set -euo pipefail
APPROVED_SPEC=/Users/prax/Development/Hermes-Projects/dr-alex-memory-architecture-v1-clean/docs/architecture/dr-alex-memory-architecture-v1/CHANGE-SPEC-v3.md
expected_manifest="$(awk -v heading='The exact agent-memory staged manifest is the following, with the six change files located only' '
  $0 == heading { wanted=1; next }
  wanted && $0 == "```text" { block=1; next }
  block && $0 == "```" { exit }
  block { print }
  END { if (!block) exit 2 }
' "$APPROVED_SPEC")"
test -n "$expected_manifest"
diff -u \
  <(printf '%s\n' "$expected_manifest" | LC_ALL=C sort) \
  <(git diff --cached --name-only | LC_ALL=C sort)
```

## 7. Baseline-relative quality evidence

Dr. Alex's canonical full test suite passes after restoring the worktree-only `data/` mode to
`0700`; `ruff check` passes. Global `ruff format --check` and global mypy have pre-existing
failures at the frozen baseline. v3 does not reformat 37 unrelated files or repair 13 unrelated
type errors. Dr. Alex changed files must pass scoped format, lint, and type checks, and its
global results must not regress. agent-memory deliberately declares pytest as its sole dev
dependency, so v3 uses its native strict OpenSpec, compile, and canonical pytest gates instead
of inventing a ruff or mypy requirement.

The prior agent-memory receipt records 1,601 passed, 3 skipped, and one warning. A fresh full run
in the isolated implementation worktree is required before commit.

## 8. Definition of done

The run is complete only when:

- all v3 normative documents and the OpenSpec delta receive every requested review and final PASS;
- each nontrivial branch is introduced test-first and fails for the expected reason;
- both focused and full suites pass;
- Dr. Alex changed-file lint, format, and type checks pass;
- agent-memory strict OpenSpec, compile, and canonical test gates pass;
- archived canonical `derived-index` and `mcp-transport` contain no legacy Boolean-as-permission
  sentence and match the frozen hardening policy;
- global baseline checks do not regress;
- code review has no unresolved blocker or major finding;
- one atomic local commit exists per repository and no push, merge, activation, or live data
  operation occurred;
- the post-commit user handoff reports both resulting commit IDs without staging a
  self-referential delivery receipt;
- the final report states that PWA lifecycle, physical isolation, deletion, and Hermes
  consolidation remain incomplete and human-gated.
