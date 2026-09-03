# Current-state verification

**As of:** 2026-08-23  
**Method:** read-only source, configuration, log, and test inspection. No private conversation body was copied.

## Verdict

The governing reports remain directionally sound, but two current-state statements need precise updates.

1. The Dr. Alex PWA gap is confirmed. `dr_alex/alexd.py` implements `/session/end`, drains buffered text, stamps telemetry, and removes the in-process session. It does not call the existing `fanout.finalize_session` function. The TUI does call that function from `DrAlexApp.on_unmount`. The one shared crash-safe fan-out exists and should be reused.
2. The Hermes therapist profile now registers the `agent-memory` MCP and exposes five tools. Current logs prove registration. No source hook or log receipt proves automatic session-end capture, consent-aware extraction, or cross-surface recall. The correct state is `manually reachable; lifecycle integration unproven`, not `unwired` and not `unified`.

## Claim matrix

| Claim | Current state | Evidence | Disposition |
|---|---|---|---|
| Hermes therapist, standalone Dr. Alex, and retired Therapy Stack are separate runtime histories | Confirmed | Distinct profile DB, Dr. Alex state, and frozen Therapy Stack tree | Keep |
| Dr. Alex TUI performs durable session fan-out | Confirmed | `dr_alex/app.py:615-651` calls `fanout.finalize_session` | Keep |
| Dr. Alex PWA performs the same fan-out | False | `dr_alex/alexd.py:449-481` ends telemetry and drops the session without calling fan-out | Implement only after durable-memory consent is explicit |
| PWA pending fragments survive session end | Confirmed | `alexd.py:457-474`; `tests/test_alexd.py:252-277` | Preserve |
| Hermes cannot access agent-memory | Stale | Therapist `config.yaml` registers MCP; logs show five tools | Replace with manual-tool availability |
| Hermes automatically commits authorized sessions to agent-memory | Unproven | No automatic caller or lifecycle plugin found; tool registration is not capture | Gate remains closed |
| High-sensitivity recall snippets and full-body reads are fully identity-gated | False | `recall.py:210-215` treats request `include_sensitive=true` as high scope without calling the launch-agent gate; `mcp.py:476-499` does the same for full-body fetch | Harden both paths before clinical adoption |
| Clinical memory is physically isolated | False | Therapist MCP points to the general `/Users/prax/agent-memory` root under the same OS account | Separate-root ticket required |
| The canonical memory suite is healthy | Partially confirmed | 1,601 tests passed, 3 skipped; `memctl doctor` exits 7 | Do not claim operational readiness |
| Universal continuity is proven | False | No end-to-end receipt spans Telegram, Hermes, PWA, deletion, backup, and restore | Keep explicit non-claim |

## Scope decision

The staged program is still justified, but sequencing is narrower than rc1. The first code slice establishes subject, paired-device ownership, and default-deny consent. No new PWA durable sink is enabled. The separate agent-memory slice hardens both high-sensitivity recall and full-body fetch against request-controlled `include_sensitive`. Physical clinical isolation and live Hermes activation remain parked behind later human-approved contracts.
