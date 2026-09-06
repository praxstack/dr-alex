# Dr. Alex

A warm, safe, **local** terminal + phone therapy-support companion. Dr. Alex Morgan runs a
single deterministic safety-first turn pipeline: crisis **triage runs first, in code**, RED
short-circuits **before** retrieval and before the model, and deterministic output gates run
before a token is ever shown. It is a support companion, not a clinician, and it never
auto-sends anything anywhere.

> If you or someone else is in danger, call your local emergency number. In India:
> **iCall 9152987821**, **Tele-MANAS 14416/1-800-891-4416**. `dr-alex --card` prints the full
> crisis card offline, with no model call.

## Install

Requires Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/). macOS (uses the Keychain for
secrets and launchd for the optional jobs).

```bash
uv tool install .            # installs the `dr-alex` console script
# or, from a source checkout, run without installing:
uv run dr-alex --version
```

PDF book ingestion is optional (`uv tool install '.[pdf]'` for PyMuPDF); `.txt`/`.md` books
work without it.

## CLI

| Command | What it does |
|---|---|
| `dr-alex` | Full warm session (Textual TUI). |
| `dr-alex "some text"` | One-shot: a single safety-first exchange, printed and done. |
| `dr-alex checkin` | Gentle nightly "how was today?" opener (TUI). `--notify` posts the fixed nightly notification (what the launchd job runs). |
| `dr-alex export --from <date> --to <date> [--redaction summary\|full]` | Date-ranged markdown + self-contained HTML for print-to-PDF. |
| `dr-alex review` | Default last-30-days export, ready to print-to-PDF. |
| `dr-alex serve` | Run `alexd` ("The Room") in the foreground on `http://127.0.0.1:18787/`. |
| `dr-alex pair` / `devices` / `revoke <id>` | Mint a one-time PWA pairing code / list / revoke paired devices. |
| `dr-alex books ingest` / `books status` | (Re)build the book RAG index / show the corpus manifest + index state. |
| `dr-alex shreya` | Friday Shreya-prep packet (local draft; never sent). |
| `dr-alex records` | Show the canonical Active File path (creating the scaffold if needed). |
| `dr-alex notion status` | Whether the Notion mirror is enabled (secrets stay in Keychain). |
| `dr-alex backup` | Git bundle, WAL-consistent encrypted state snapshot, and encrypted private records archive. |
| `dr-alex eval --once` | G13 nightly eval (normally run by the disabled cron). |
| `dr-alex improve --once [--dry-run]` / `improve status` / `improve revert` | G22 nightly persona keep-or-revert loop / history / undo last accepted change. |
| `dr-alex --card` | Print the crisis card (pure, no LLM) and exit. |
| `dr-alex --version` | Version. |

## Safety note

The safety invariants are non-negotiable and gated by the test suite (see `AGENTS.md`):
triage-first, RED short-circuits before the model, a **single LLM entrypoint**
(`llm.complete`, driven by `engine.run_turn`), deterministic output gates, and the
**golden crisis corpus gate** (100% RED recall on the curated corpus). Every free-text value
in `state.db` is Fernet-encrypted at rest; the encryption key lives in the macOS Keychain.
Privacy kill-switches (`DR_ALEX_TELEMETRY_OFF`, `DR_ALEX_MEMORY_OFF`, `DR_ALEX_NOTION_OFF`,
`DR_ALEX_VOICE_OFF`) and every other `DR_ALEX_*` env var are documented authoritatively in the
`dr_alex/config.py` module docstring.

## Secrets (macOS Keychain)

Keys and tokens live in the Keychain under the `dr-alex` service, never in the clear. The
transcript/state encryption key is created automatically on first use. The optional Notion
mirror token is added manually — run `dr-alex notion status` for the exact
`security add-generic-password` command.

## Phone access (The Room PWA)

`alexd` binds **loopback only** (`127.0.0.1:18787`); a hard assert refuses `0.0.0.0`/LAN/any
tunnel. The phone reaches it over **Tailscale** (`tools/tailscale-setup.sh` → `tailscale serve
https / 127.0.0.1:18787`), never by widening the bind. Every endpoint except `/crisis`,
`/healthz`, `/pair` and the static shell requires a paired device token (`dr-alex pair`).

## Scheduled jobs (disabled by default)

> Note (updated 2026-09-05): the shipped plists ship inert as described below, BUT
> `com.prax.dralex-alexd` has been enabled and IS RUNNING via launchd (KeepAlive on crash,
> RunAtLoad). That's intended — alexd is the live loopback daemon serving The Room on
> 127.0.0.1:18787 (moved from 8787 to avoid Cursor MCP OAuth callbacks).
> Don't re-enable the others without deciding to.

The launchd agents in `tools/launchd/` ship **inert** (`Disabled` true, not loaded): alexd,
the nightly check-in, the G13 eval, and the G22 self-improve loop. Enable one deliberately,
e.g.:

```bash
cp tools/launchd/com.prax.dralex-alexd.plist ~/Library/LaunchAgents/ \
  && launchctl load -w ~/Library/LaunchAgents/com.prax.dralex-alexd.plist
```

Each plist's header documents its own enable command and grace-window behaviour.

## Model and Hermes routing

The model backend uses the existing **Codex subscription**, through the installed Hermes
Codex OAuth transport. No Claude subscription, Claude login, or Claude CLI is required.
The transport receives only the assembled turn context over stdin, has no tools, and does
not persist prompts or provider error dumps. It currently uses `gpt-5.6-sol`.

The Hermes `therapist` profile routes Desktop and gateway chats to the same local Dr. Alex
engine at `127.0.0.1:18787/v1`. Native session IDs retain conversation identity. Provider
fallbacks are disabled so an upstream error cannot silently bypass the local gates.
Pairing credentials remain in the private profile environment. The standalone Room UI
at `http://127.0.0.1:18787/` uses this same engine and restores its session on refresh.

`/healthz` checks local infrastructure. `/readyz` additionally requires a successful model
completion within 15 minutes. An authenticated `POST /model/probe` checks the actual Codex
connection with a synthetic prompt and no personal context.

Hermes raw conversations remain in its profile database with automatic pruning disabled.
After triage, matching historical excerpts are retrieved from that database alongside book
excerpts. Raw retention and retrieval are separate: each turn retrieves a bounded set of
matches, rather than fitting the entire history into every prompt.

The old Claude mobile recreation kit is historical material, not an active backend or
synchronized fallback. When the Mac is unavailable, the Room's cached crisis card remains
offline; model chat requires the Mac and its configured subscription connection.

Backups include private continuity, pending session state, records, pairing data and local
book data in an encrypted archive. Keep the macOS Keychain recovery path: a same-Mac restore
does not prove recovery after losing the encryption key.

Current repair evidence and the open subagent evaluation matrix live in
[docs/repair-2026-09-06](docs/repair-2026-09-06/).

## Development

See `AGENTS.md` for build/test commands, conventions, and the safety invariants that must
never regress. In short: `uv run pytest -q`.
