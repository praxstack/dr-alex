# AGENTS.md

Guidance for agents (and humans) working on Dr. Alex. This repo is agent-developed and ships
a nightly self-improvement loop that edits the persona under a gate — so the safety invariants
below are load-bearing and enforced by the test suite. **Do not weaken them.**

## Build / test

```bash
uv run pytest -q          # the whole suite is the gate — keep it green
uv run pytest tests/test_triage.py     # focused run
uv run dr-alex --version  # smoke-check the console script
```

- Python ≥ 3.12, managed with `uv`. No network in tests (an in-memory `keyring` backend and
  fake LLM/subprocess seams are installed via `tests/conftest.py`).
- Every change lands as its own commit, tested, with the suite green.

## Architecture map (one screen)

- **`safety/triage.py`** — GREEN/AMBER/RED classifier. Runs FIRST, in code. Design bias:
  a false-positive RED is acceptable; a false-negative is not.
- **`safety/`** — crisis card (`--card`), crisis prescreen (debounce bypass), crisis
  questioning discipline (G1), context guard.
- **`dr_alex/engine.py`** — `run_turn`, THE single safety-first turn used by the TUI, the
  one-shot CLI, and `alexd`. RED short-circuits here before retrieval and before the model.
- **`dr_alex/llm.py`** — `complete()` is THE single model entrypoint (Directive 1). It raises
  if ever called on a RED turn. All model use (turns, gate regeneration, continuity, improve)
  routes through it.
- **`dr_alex/gates.py`** — deterministic output gates; run before any token is delivered.
- **`dr_alex/alexd.py`** — the loopback-only FastAPI front door ("The Room" PWA). Transport
  only; every turn still goes through `engine.run_turn`.
- **`dr_alex/statedb.py`** — encrypted local telemetry (`state.db`); free text Fernet-encrypted
  at rest. **`dr_alex/memstore.py`** — durable memory (memctl CLI). **`dr_alex/records.py`** —
  the canonical human-readable Active File.
- **`dr_alex/improve.py`** — G22 nightly persona keep-or-revert loop (propose → gate →
  benchmark → keep/revert). Disabled by default.
- **`dr_alex/timeutil.py`** — the single home for IST + UTC/ISO time helpers.
- **`dr_alex/config.py`** — runtime config + the authoritative `DR_ALEX_*` env-var reference
  (module docstring).

## Safety invariants that must never regress

1. **Triage-first.** `safety.triage` classifies before anything else in a turn.
2. **RED short-circuits.** A RED turn never reaches retrieval or the model; it returns the
   crisis card. `llm.complete()` raises on a RED tier as a backstop.
3. **Single LLM entrypoint.** `llm.complete()` is the only place a model is invoked.
   `tests/test_single_llm_entrypoint.py` enforces this by grep/AST — never add a second
   subprocess/model call site; route through `complete()` with a directive instead.
4. **Golden-gate = 100% RED recall.** `improve.check_golden_red_sensitivity` must hold 100%
   RED recall on the curated `tests/golden_crisis/corpus.json`, and non-RED cases must classify
   to their expected tier (specificity). The self-improve loop reverts any persona edit that
   drops this.
5. **Frozen safety sections are integrity-checked**, not just marker-present: an edit that
   overlaps a frozen safety section is rejected (`improve.check_frozen_invariants`).
6. **Deterministic output gates** run before delivery on every non-RED turn.
7. **Encryption at rest.** Every free-text value in `state.db` is Fernet-encrypted before it
   touches disk; the key lives in the macOS Keychain. Only ints/enums/timestamps/hashes sit
   in the clear (the plaintext allowlist).
8. **Loopback-only alexd.** The bind guard refuses anything but `127.0.0.1`/`::1`. The phone
   reaches it via Tailscale, never by widening the bind.

If a change would alter any of these behaviours, STOP and surface it — do not silently adjust
a safety test to make a change pass.

## Conventions

- Telemetry/logging is body-free (R3): counts, enums, hashes — never therapy text.
- Everything fails safe: a broken config/store/telemetry path degrades to a conservative no-op
  rather than breaking a turn.
- New `DR_ALEX_*` env vars go in the `dr_alex/config.py` docstring reference.
- Lint/format/type-check config lives in `pyproject.toml` (ruff + mypy); run `ruff check` and
  `ruff format` before committing.
