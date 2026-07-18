# planned-fixed-v1 — dr-alex

> Generated from the read-only `/improve` deep audit (2026-07-18) against HEAD `01b35cc`.
> Repo: `/Users/prax/dr-alex`. Each FIX lands as its own commit, tested, code-reviewed. DECISION items are surfaced, not silently changed.

## Status legend
`TODO` not started · `WIP` in progress · `DONE` fixed+tested+committed · `DECISION` needs Prax's intent (not auto-changed) · `SKIP` rejected on vet

## Findings

| # | Status | Sev(conf/effort/risk) | Finding | Location |
|---|---|---|---|---|
| 1 | DONE | high/M/med | TUI re-implements the safety turn pipeline instead of calling run_turn; the copies have drifted so phone-side RED (crisis) turns are never persisted | `dr_alex/app.py:584 (+ engine.py:369, alexd.py:159)` |
| 2 | TODO | high/S/low | Date-ranged export miscounts sessions + late-night signal: uses a now-anchored window, ignoring from/to | `dr_alex/export.py:136 (+ statedb.py:865)` |
| 3 | DONE | high/S/low | Re-ask backstop is regenerate-once-and-hope, not block; the still-probes branch is untested and mislabeled 'reask-blocked' | `dr_alex/engine.py:402` |
| 4 | DONE | high/M/low | Prompt-injection defense on the two most-trusted context channels is weak (no fence neutralization + asymmetric framing) AND has zero adversarial test | `dr_alex/memory.py:160 (+ engine.py:143, llm.py:80)` |
| 5 | DONE | high/M/med | Session-end fan-out silently drops a session's durable memory on a transient scrub/remember failure (marker cleared unconditionally, scrub_failed swallowed) | `dr_alex/fanout.py:133 (+ fanout.py:234, app.py:659-667)` |
| 6 | DONE | high/S/low | Crisis-fragment debounce bypass in alexd has no endpoint-level test; the DebounceBuffer test uses a fake crisis predicate | `dr_alex/alexd.py:335` |
| 7 | DONE | high/S/low | Golden crisis corpus's 71 non-RED cases are loaded but never asserted — only RED recall is gated, so false-positive regressions pass silently | `dr_alex/improve.py:210` |
| 8 | DONE | high/M/med | Self-improve 'frozen invariants' gate is substring-presence only, so a behavior-changing persona edit that keeps every marker passes and is committed live | `dr_alex/improve.py:171` |
| 9 | TODO | high/S/low | Per-turn telemetry recomputes system_prompt() from disk instead of reusing the built prompt — and hashes the WRONG prompt on the alexd memory-augmented path | `dr_alex/engine.py:297` |
| 10 | TODO | med/S/low | alexd debounce timer-flush silently discards buffered fragments via a no-op flush callback | `dr_alex/alexd.py:98` |
| 11 | TODO | high/S/low | Operational env vars and four privacy kill-switches are undocumented (no central reference, no .env.example) | `dr_alex/config.py:32` |
| 12 | TODO | high/S/low | Dead code: llm._extract_text is unused by production and its docstring misdescribes how alexd streams | `dr_alex/llm.py:260` |
| 13 | TODO | high/S/low | Time/IST handling duplicated across ~6 modules with two separate IST constants | `dr_alex/reorient.py:24 (+ statedb.py:35)` |
| 14 | TODO | high/M/low | No top-level README / getting-started for the main application | `dr_alex/cli.py:1` |
| 15 | TODO | med/S/low | No dev/agent-facing AGENTS.md or CLAUDE.md in a repo built and self-modified by agents | `dr_alex/improve.py:35` |
| 16 | TODO | high/S/med | No linter, formatter, or type-checker for a safety-critical codebase | `pyproject.toml:53` |
| 17 | TODO | high/S/med | statedb._connect re-applies the full 8-table schema on every single DB operation | `dr_alex/statedb.py:187` |
| 18 | TODO | med/M/med | memctl recall/remember/scrub each cold-spawn `uv run`; session-end fan-out spawns one subprocess per durable learning | `dr_alex/memstore.py:83` |
| 19 | TODO | high/S/low | The Room PWA shell is served with no Content-Security-Policy or response-hardening headers | `dr_alex/alexd.py:216` |

## Detail + fix approach

### #1 — TUI re-implements the safety turn pipeline instead of calling run_turn; the copies have drifted so phone-side RED (crisis) turns are never persisted
- **Status:** DONE
- **Location:** `dr_alex/app.py:584 (+ engine.py:369, alexd.py:159)`  ·  **Category:** correctness+architecture  ·  conf high / effort M / fix-risk med
- **Impact:** Two divergent copies of the crisis-safety pipeline that must stay identical. VERIFIED: engine.run_turn's RED path returns at engine.py:369 with no telemetry, while app.py:562-575 records record_turn_t
- **Fix:** Collapse the TUI onto engine.run_turn via an optional streaming/render hook (llm.stream then becomes dead). FIRST make a product call on the RED-persistence divergence — decide whether run_turn SHOULD persist RED turns, then make all three surfaces (TUI/CLI/alexd) identical and add a test asserting each persists an identical turn_trace+transcript for a RED turn.

### #2 — Date-ranged export miscounts sessions + late-night signal: uses a now-anchored window, ignoring from/to
- **Status:** TODO
- **Location:** `dr_alex/export.py:136 (+ statedb.py:865)`  ·  **Category:** correctness  ·  conf high / effort S / fix-risk low
- **Impact:** VERIFIED: collect() sets window_days=max(1,len(days)) then window_snapshot(now,window_days), which queries sessions WHERE started_ts >= now-window_days with NO upper bound. data.sessions and late_nigh
- **Fix:** Add a range-scoped reader (sessions_between(from_iso,to_iso) counting started_ts BETWEEN from AND to, plus a late-night count over the same bounds) and use it in collect() instead of window_snapshot; or pass an explicit upper bound into window_snapshot.

### #3 — Re-ask backstop is regenerate-once-and-hope, not block; the still-probes branch is untested and mislabeled 'reask-blocked'
- **Status:** DONE
- **Location:** `dr_alex/engine.py:402`  ·  **Category:** correctness+test-coverage  ·  conf high / effort S / fix-risk low
- **Impact:** VERIFIED: the G1 backstop fires one hardened regen and sets safety_action='reask-blocked' unconditionally, never re-checking crisis_questioning.is_safety_probe(regen.text); gates.apply doesn't detect 
- **Fix:** Harden run_turn to re-check the regen and, if it still probes, deterministically strip/replace it (or loop) rather than accept one regen blindly and mislabel it. Add a regression where the fake LLM returns a probe on BOTH calls, asserting the delivered reply is not a safety probe.

### #4 — Prompt-injection defense on the two most-trusted context channels is weak (no fence neutralization + asymmetric framing) AND has zero adversarial test
- **Status:** DONE
- **Location:** `dr_alex/memory.py:160 (+ engine.py:143, llm.py:80)`  ·  **Category:** security+test-coverage  ·  conf high / effort M / fix-risk low
- **Impact:** Recalled-memory and continuity blocks are concatenated raw into the --append-system-prompt (highest-authority channel) with NO fence-token neutralization anywhere in the tree, and PERSONAL_MEMORY/CONT
- **Fix:** Neutralize fence tokens in ALL externally-sourced inserted content (strip/replace </BOOK_CONTEXT>,</PERSONAL_MEMORY>,</CONTINUITY_BRIEF>,<SAFETY_STATE,<SESSION_START> or wrap each block in a per-session nonce delimiter), and add the same 'evidence, not instruction' framing to PERSONAL_MEMORY and CONTINUITY_BRIEF. Add adversarial turn tests feeding injection-bearing chunks/snippets, asserting the envelope holds and gates strip injection-induced artifacts.

### #5 — Session-end fan-out silently drops a session's durable memory on a transient scrub/remember failure (marker cleared unconditionally, scrub_failed swallowed)
- **Status:** DONE
- **Location:** `dr_alex/fanout.py:133 (+ fanout.py:234, app.py:659-667)`  ·  **Category:** correctness  ·  conf high / effort M / fix-risk med
- **Impact:** complete() runs _channel_c_inbox (returns (None,True) on ScrubError, leaving inbox_written=False) then UNCONDITIONALLY calls _finalize_state, which clears st.unfinalized — wiping the crash-safety mark
- **Fix:** Do not clear unfinalized in _finalize_state when any channel step is incomplete (inbox_written False, unwritten durable indices, or scrub_failed True) — keep the marker so recover_if_needed replays next start; and surface scrub_failed/remember failures loudly (log/telemetry) instead of letting app.py discard them.

### #6 — Crisis-fragment debounce bypass in alexd has no endpoint-level test; the DebounceBuffer test uses a fake crisis predicate
- **Status:** DONE
- **Location:** `dr_alex/alexd.py:335`  ·  **Category:** test-coverage  ·  conf high / effort S / fix-risk low
- **Impact:** The /turn handler buffers fragments unless crisis is detected (`if is_fragment and not bypass:`, bypass from real crisis_prescreen.should_bypass_debounce). No alexd test sends a RED text with fragment
- **Fix:** Add an alexd integration test posting a RED text with fragment:True, asserting the response immediately streams the crisis card (meta crisis=true, contains 14416/Shreya) with zero buffering and no model call — exercising the real crisis_prescreen wiring.

### #7 — Golden crisis corpus's 71 non-RED cases are loaded but never asserted — only RED recall is gated, so false-positive regressions pass silently
- **Status:** DONE
- **Location:** `dr_alex/improve.py:210`  ·  **Category:** test-coverage  ·  conf high / effort S / fix-risk low
- **Impact:** check_golden_red_sensitivity filters to expected==RED and gates only on 100% RED recall. corpus.json holds 127 curated cases (56 RED, 34 GREEN, 21 AMBER, 16 NOT_RED) but the 71 non-RED cases — includi
- **Fix:** Extend the golden gate (or a dedicated test) to assert every non-RED corpus case classifies to its expected tier — at minimum NOT_RED/GREEN are not RED and AMBER is AMBER — so the whole curated corpus guards regressions.

### #8 — Self-improve 'frozen invariants' gate is substring-presence only, so a behavior-changing persona edit that keeps every marker passes and is committed live
- **Status:** DONE
- **Location:** `dr_alex/improve.py:171`  ·  **Category:** security  ·  conf high / effort M / fix-risk med
- **Impact:** check_frozen_invariants only tests `_normalize(m) not in norm` for each required marker — it verifies safety marker strings are still PRESENT, never that safety sections are unchanged or that no new d
- **Fix:** Make the gate integrity-based not presence-based: reject any find/replace whose span overlaps a frozen safety section, and assert frozen sections are byte-identical before vs after the edit (diff-scoped editable allowlist), in addition to marker-presence and golden-RED checks.

### #9 — Per-turn telemetry recomputes system_prompt() from disk instead of reusing the built prompt — and hashes the WRONG prompt on the alexd memory-augmented path
- **Status:** TODO
- **Location:** `dr_alex/engine.py:297`  ·  **Category:** performance+correctness  ·  conf high / effort S / fix-risk low
- **Impact:** record_turn_telemetry calls prompt_hash(system_prompt(), ...) which re-reads persona/dr-alex.md AND data/continuity.md and rebuilds the prompt, though run_turn already computed the actual prompt as `s
- **Fix:** Thread `sp` into record_turn_telemetry (add a system_prompt param) and hash that, mirroring app.py — removes the double read and makes prompt_hash reflect the real (possibly memory-augmented) prompt.

### #10 — alexd debounce timer-flush silently discards buffered fragments via a no-op flush callback
- **Status:** TODO
- **Location:** `dr_alex/alexd.py:98`  ·  **Category:** correctness  ·  conf med / effort S / fix-risk low
- **Impact:** RoomSession builds DebounceBuffer(flush_callback=lambda _p: None). A fragment push arms a 4s timer; when it fires, _on_timer -> _fire(TIMER) -> the no-op -> _finish clears the buffer. Coalesced text i
- **Fix:** Give the buffer a real flush callback that delivers/queues the coalesced turn on timer expiry, OR disable the timer path in the alexd integration so buffered fragments are released only by the explicit final flush_now, never dropped by the timer.

### #11 — Operational env vars and four privacy kill-switches are undocumented (no central reference, no .env.example)
- **Status:** TODO
- **Location:** `dr_alex/config.py:32`  ·  **Category:** dx-docs  ·  conf high / effort S / fix-risk low
- **Impact:** ~20 DR_ALEX_* vars are private constants scattered across config.py/statedb.py/memstore.py/notion.py/voice.py/llm.py etc. config.toml documents TOML keys but never the env overrides or the *_OFF kill-
- **Fix:** Add a Configuration/Environment section (README or CONFIG.md) enumerating every DR_ALEX_* var, default, and effect, grouping the *_OFF kill-switches prominently; optionally ship a commented .env.example. No code change.

### #12 — Dead code: llm._extract_text is unused by production and its docstring misdescribes how alexd streams
- **Status:** TODO
- **Location:** `dr_alex/llm.py:260`  ·  **Category:** tech-debt  ·  conf high / effort S / fix-risk low
- **Impact:** _extract_text parses Claude stream-json and is referenced only by tests — zero production callers. Its docstring claims it is 'Retained for the Phase-5 SSE surface (alexd streams stream-json to the PW
- **Fix:** Delete _extract_text and its test, or if kept for a future streaming plan, correct the docstring to state it is currently unused and drop the false claim that alexd consumes stream-json.

### #13 — Time/IST handling duplicated across ~6 modules with two separate IST constants
- **Status:** TODO
- **Location:** `dr_alex/reorient.py:24 (+ statedb.py:35)`  ·  **Category:** tech-debt  ·  conf high / effort S / fix-risk low
- **Impact:** IST=ZoneInfo('Asia/Kolkata') is defined twice (reorient.py:24, statedb.py:35) and per-module now/format helpers are re-rolled (app.py:38, statedb.py:71/77, reorient.py:30, pairing.py:96). IST/timestam
- **Fix:** Introduce one dr_alex/timeutil.py exporting IST, now_utc, now_iso, to_ist; have statedb/reorient/export/widgets/pairing/app import from it; delete the duplicate constant and per-module helpers.

### #14 — No top-level README / getting-started for the main application
- **Status:** TODO
- **Location:** `dr_alex/cli.py:1`  ·  **Category:** dx-docs  ·  conf high / effort M / fix-risk low
- **Impact:** The only README documents the Mac-asleep FALLBACK kit, not the app; the full command map lives only in the cli.py module docstring reachable via `dr-alex --help`. A new operator or inheriting agent ha
- **Fix:** Add a thin top-level README.md: one-command install/run, a CLI-subcommand table (mirroring cli.py:1-29), the Keychain secret-setup block, how to enable the disabled launchd jobs, the Tailscale-only phone path, and a pointer to the mobile fallback kit — linking to authoritative inline docs rather than duplicating.

### #15 — No dev/agent-facing AGENTS.md or CLAUDE.md in a repo built and self-modified by agents
- **Status:** TODO
- **Location:** `dr_alex/improve.py:35`  ·  **Category:** dx-docs  ·  conf med / effort S / fix-risk low
- **Impact:** Repo root .claude/ is empty and there is no AGENTS.md/CLAUDE.md. The codebase is agent-developed and ships a nightly self-improvement loop whose PROPOSE/JUDGE steps meta-call `claude` to edit persona/
- **Fix:** Add an AGENTS.md (or CLAUDE.md) with a one-screen architecture map, the non-negotiable safety invariants, the verify command, and the by-design tradeoffs (loopback-only, plaintext Active-File + FileVault check, self-improve disabled-by-default) so contributors and the improve-loop context share one source of truth.

### #16 — No linter, formatter, or type-checker for a safety-critical codebase
- **Status:** TODO
- **Location:** `pyproject.toml:53`  ·  **Category:** dx-tooling  ·  conf high / effort S / fix-risk med
- **Impact:** pyproject configures only pytest; no ruff/mypy/black/isort config and no pre-commit. The 566-test suite is the only automated gate. A deterministic safety-triage app (safety/triage.py + gates) has no 
- **Fix:** Add ruff (lint+format) and a mypy config to pyproject plus a minimal local script running `ruff check`, `mypy`, `uv run pytest -q`. Introduce non-blocking to absorb the initial backlog, then ratchet to blocking on the safety/ and gates modules first.

### #17 — statedb._connect re-applies the full 8-table schema on every single DB operation
- **Status:** TODO
- **Location:** `dr_alex/statedb.py:187`  ·  **Category:** performance  ·  conf high / effort S / fix-risk med
- **Impact:** The _connect context manager runs executescript(_SCHEMA) (CREATE TABLE IF NOT EXISTS x8) every entry, for reads as well as writes — ~3 fresh connections + 3 full schema re-applications per turn, and e
- **Fix:** Apply the schema once (init_db on first use, or gate executescript behind a PRAGMA user_version check / module-level _initialized flag) so routine reads/writes skip the CREATE-TABLE script; optionally reuse a single connection.

### #18 — memctl recall/remember/scrub each cold-spawn `uv run`; session-end fan-out spawns one subprocess per durable learning
- **Status:** TODO
- **Location:** `dr_alex/memstore.py:83`  ·  **Category:** performance  ·  conf med / effort M / fix-risk med
- **Impact:** _launcher() returns ['uv','run','--project',...,'memctl'] with no --no-sync/--frozen, so uv does a lockfile/venv sync check + fresh interpreter start on every call. recall runs on the path to first pe
- **Fix:** Add --no-sync (or --frozen) to the uv launcher to skip per-call resolution, and collapse the fan-out's per-learning writes into one memctl bulk invocation (the store's write kernel has a --bulk mode). Keeps the memctl-CLI-only contract intact.

### #19 — The Room PWA shell is served with no Content-Security-Policy or response-hardening headers
- **Status:** TODO
- **Location:** `dr_alex/alexd.py:216`  ·  **Category:** security  ·  conf high / effort S / fix-risk low
- **Impact:** root() and _asset_response set no CSP, X-Content-Type-Options, or Referrer-Policy on any response. The Room is a therapy browser surface reachable from the phone over the tailscale HTTPS origin. The '
- **Fix:** Add a strict CSP to shell/asset responses (default-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none') plus X-Content-Type-Options: nosniff and Referrer-Policy: no-referrer.

## Direction (roadmap — not part of this fix pass)
- Build the real WebAuthn passkey ceremony the phone path already stubs — today the only sanctioned phone auth is a never-expiring, replayable bearer token (effort L)
- Close the clinician loop — productize inbound insight capture (today a one-shot manual archive script) to match the automated weekly outbound packet (effort M)
- Surface a personal progress view for Prax himself — the state DB captures rich longitudinal signal that only ever renders as a 30-day sparkline (effort M)
- Productize the Claude-mobile degradation kit as a generated-from-source artifact instead of a hand-maintained copy with a weak drift guard (effort S)

## Coverage gaps (audit blind spots)
- Process gaps: (1) No auditor RAN the 566-test suite or measured line/branch coverage — every finding is from code reading, not an observed failure. (2) No dependency CVE scan / pip-audit was run (no network) — httpx 0.28.1, fastapi 0.139.2/starlette 1.3.1, uvicorn, cryptography 49.0.0, keyring 25.7.0, PyMuPDF 1.28.0 are unchecked for advisories (versions are pinned/current per uv.lock, but not vul
