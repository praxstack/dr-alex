# OAuth callback investigation, September 5, 2026

September 6 follow-up: the obsolete `cursor-origin` was removed from local Git
configuration after saving a private backup. The full suite now passes (650 passed,
2 skipped). The September 5 observations below are retained as dated evidence;
its uncommitted-work paragraph describes that earlier checkpoint.

Confirmed: the displayed JSON 404 came from alexd, not Cursor. Two applications
were listening on different address families of the same localhost port.
No browser privacy, proxy, DNS, IPv6, or extension settings were changed.

```text
Before
  Cursor -> Mem0 login -> Zen -> localhost:8787/callback
                                  +-- IPv4: alexd -> JSON 404
                                  +-- IPv6: Cursor -> OAuth handler

After
  Cursor -> Mem0 login -> Zen -> localhost:8787/callback
                                  +-- IPv4: Cursor
                                  +-- IPv6: Cursor
  alexd -> 127.0.0.1:18787 (loopback only)
```

## Evidence and causal test

- Initial `lsof`: PID 779, the editable uv installation of Dr. Alex, owned
  `127.0.0.1:8787`; Cursor MCP PID 6627 owned `[::1]:8787`.
- Direct IPv4 `/callback` returned `404 {"detail":"Not Found"}`, exactly the
  screenshot. IPv6 returned Cursor's different plain-text missing-route response
  when no OAuth parameters were supplied.
- Computer History records the Mem0 authorization request and failed localhost
  callback at 16:17 UTC. Its available segments span September 4-5, so it cannot
  establish every failure over the reported preceding 5-6 days (or 56 days).
- In Zen, changing only the existing callback authority to `[::1]:8787` produced
  Cursor's “Authorization complete” page at 16:23:53 UTC. The OAuth parameters
  were preserved and are omitted from this report.
- Cursor's installed extension contains the fixed `http://localhost:8787/callback`
  redirect. Its [official MCP docs](https://prod.cursor.com/docs/mcp) document
  that shared desktop redirect. A [Cursor support response](https://forum.cursor.com/t/mcp-oauth-binds-to-ipv6-loopback-breaking-127-0-0-1-mcp-redirect/165441/5)
  explicitly describes conflicts with another local service on that port.
- [RFC 8252 section 7.3](https://www.rfc-editor.org/rfc/rfc8252.html#section-7.3)
  describes loopback IP literals, available ports and IPv4/IPv6 listener handling.
  Cursor's fixed localhost callback creates a collision risk across MCP providers.

Zen reached a real HTTP server. It was not a connection-refused or certificate
failure. The OpaqueResponseBlocking console entry concerned `favicon.ico`;
it does not explain why the main callback reached alexd's missing route.
Another browser choosing IPv6 might appear to fix the issue while the underlying
port conflict remained. Other applications using different callback ports need
separate evidence; this diagnosis is confirmed for the shown Cursor/Mem0 flow.

## Repair and verification

Changed alexd's default port to 18787, updated CLI/README/Tailscale guide
references, and added a CLI default-port regression. The test failed at 8787
before the production change and passed afterward. `--port=` remains available.
No safety gate, bind guard, account configuration, credential, or data changed.

The installed uv tool is editable against this checkout. The existing launchd
job runs `dr-alex serve`, so restarting the idle daemon picks up the corrected
default without rewriting the enabled/disabled scheduling policy. There were
no established connections when it was stopped gracefully.

After restart, `/healthz` on 18787 returned 200 with room shell, crisis card and
state database checks true. On a fresh Cursor authentication attempt, `lsof`
showed Cursor alone on **both** `127.0.0.1:8787` and `[::1]:8787`, with alexd
on `127.0.0.1:18787`. No Tailscale installation/mapping was present to migrate.
Local bookmarks to The Room must now use port 18787. Browser storage is
origin-specific, so an existing local PWA may need pairing at the new address;
its old-origin storage and server-side device records were not deleted.

| Check | Result |
| --- | --- |
| Focused alexd suite | 27 passed |
| Full suite with login SSH agent available | 612 passed, 2 skipped, 1 existing remote-policy failure |
| Ruff check on touched Python files | Passed |
| Ruff format check | Existing formatting debt in both touched files; unchanged HEAD copies also fail |
| Shell syntax / diff whitespace | Passed |
| Dr. Alex deployed health | 200, loopback-only, all reported checks true |
| Cursor listener after fresh login request | IPv4 and IPv6 both owned by Cursor |

The full-suite failure is `test_only_sanctioned_git_remotes`: this checkout has
an existing `cursor-origin` pointing to `https://origin.cursor.com/praxstack/dr-alex.git`,
while the protected guard permits only the GitHub `origin`. That remote and the
guard were preserved. The first suite run also lacked access to the login SSH
agent; reconnecting that existing agent resolved the temporary test-commit
failures without disabling signing.

Source repairs remain uncommitted because AGENTS.md requires a green full suite
before committing. No remote was removed, no gate weakened, and no code pushed.
Unrelated untracked status reports were preserved.

## Separate remaining Mem0 failure

The fresh login progressed through Mem0's existing browser session to its
organization/project selector. It then displayed:

> Daily API key limit reached (5). Try again tomorrow.

This is a provider-side provisioning limit, separate from the localhost routing
bug. Cursor's Local Mem0 connection reports Connected, while Cloud still reports
Needs Authentication. The callback success page alone is not proof of completed
cloud token exchange. No further key-creation attempts were made after that
message, and no existing memories/keys were deleted to work around the limit.
Retry the Cloud authentication once Mem0's limit resets; the localhost port
collision has been removed. The provider's exact reset timezone was not verified.

The private diagnostic scratch directory is
`/var/folders/n0/4hwt0zvx1vx60vk91xlm1y700000gn/T/oauth-loopback-audit-beecmbli`.
Raw callback credentials are not included in this report or the source diff.
