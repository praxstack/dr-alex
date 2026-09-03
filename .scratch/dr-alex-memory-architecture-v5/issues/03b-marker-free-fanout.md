# Ticket 03B: Finalize one granted session through synthetic sinks

**What to build:** A fully granted PWA session finalizes exactly once through injected synthetic seams, reusing one marker-free fanout implementation shared with the TUI.

**Blocked by:** 03A

**Status:** ready-for-agent

- [ ] `complete_digest` contains the existing sink-writing behavior but no global marker call; legacy `fanout.complete` delegates to it and stays green.
- [ ] Writer enabled plus a synthetic runner stores a Fernet-encrypted payload, runs deterministic synthetic sink steps, and returns `finalized`.
- [ ] Writer enabled without a runner returns `finalization_unavailable` / HTTP 503 and keeps encrypted recovery payload.
- [ ] Persisted DB, WAL, JSON, and logs contain no synthetic body or digest plaintext.
- [ ] Completed-session retry returns the stored body-free receipt and does not re-extract under a changed policy version.
- [ ] D1-F05, D1-F09, D1-F11, D1-F15 pass.
