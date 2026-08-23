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
| `dr-alex serve` | Run `alexd` ("The Room") in the foreground on `http://127.0.0.1:8787/`. |
| `dr-alex pair` / `devices` / `revoke <id>` | Mint a one-time PWA pairing code / list / revoke paired devices. |
| `dr-alex books ingest` / `books status` | (Re)build the book RAG index / show the corpus manifest + index state. |
| `dr-alex shreya` | Friday Shreya-prep packet (local draft; never sent). |
| `dr-alex records` | Show the canonical Active File path (creating the scaffold if needed). |
| `dr-alex notion status` | Whether the Notion mirror is enabled (secrets stay in Keychain). |
| `dr-alex backup` | G19 durability: git bundle + encrypted `state.db` snapshot. |
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

`alexd` binds **loopback only** (`127.0.0.1:8787`); a hard assert refuses `0.0.0.0`/LAN/any
tunnel. The phone reaches it over **Tailscale** (`tools/tailscale-setup.sh` → `tailscale serve
https / 127.0.0.1:8787`), never by widening the bind. Every endpoint except `/crisis`,
`/healthz`, `/pair` and the static shell requires a paired device token (`dr-alex pair`).

## Scheduled jobs (disabled by default)

> Note (2026-08-23): the shipped plists ship inert as described below, BUT
> `com.prax.dralex-alexd` has been enabled and IS RUNNING via launchd (KeepAlive on crash,
> RunAtLoad). That's intended — alexd is the live loopback daemon serving The Room on
> 127.0.0.1:8787. Don't re-enable the others without deciding to.

The launchd agents in `tools/launchd/` ship **inert** (`Disabled` true, not loaded): alexd,
the nightly check-in, the G13 eval, and the G22 self-improve loop. Enable one deliberately,
e.g.:

```bash
cp tools/launchd/com.prax.dralex-alexd.plist ~/Library/LaunchAgents/ \
  && launchctl load -w ~/Library/LaunchAgents/com.prax.dralex-alexd.plist
```

Each plist's header documents its own enable command and grace-window behaviour.

## Mobile fallback

When the Mac (the real Dr. Alex) is asleep, `docs/claude-mobile-dr-alex/` is a recreation kit
for a lightweight "Dr. Alex" Project inside the native Claude mobile app — a warm, safe voice
to reach in the interim. It is a kit, not code.

## Development

See `AGENTS.md` for build/test commands, conventions, and the safety invariants that must
never regress. In short: `uv run pytest -q`.
