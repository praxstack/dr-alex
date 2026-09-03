# Ticket 03D: Preserve legacy marker compatibility and close D1

**What to build:** Existing TUI recovery remains compatible while newly saved markers protect digest content at rest, and the whole D1 slice passes its frozen gates.

**Blocked by:** 03C

**Status:** ready-for-agent

- [ ] Legacy plaintext marker fixtures load; their next save contains `digest_enc` only.
- [ ] Marker decryption failure remains visibly pending and emits class-only logs.
- [ ] D1-F16, D1-F17 and all D1-S01..S05 pass.
- [ ] Full suite, Ruff, format, version smoke, protected hashes, source guards, and persisted-file scans pass.
- [ ] Net implementation+test diff is no more than 2,100 lines from `e0dad8a3`.
- [ ] Fresh standards, specification, security/privacy, and original-spec validator reviews return zero blockers and zero majors.
- [ ] Only reviewed repository-scoped commits exist; branch remains local, unmerged, unpushed, and inactive.
