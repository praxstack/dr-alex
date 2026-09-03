# 03: Add encrypted synthetic finalization operations

**What to build:** Reuse the existing fan-out implementation through one marker-free completion seam. Add encrypted, per-session, replay-safe PWA operations with current-consent checks and fenced leases. Keep the production writer disabled and allow synthetic sinks only.

**Blocked by:** 02: Bind PWA sessions and transcript writes to current policy.

**Status:** ready-for-agent

- [ ] `D1-F01` through `D1-F17` pass for terminal outcomes, encryption, concurrency, replay, leases, response loss, and legacy marker migration.
- [ ] `RC4-R01` through `RC4-R08` pass, including consent-before-claim, null terminal leases, ended-session handling, and default-no-operation behavior.
- [ ] No live PWA sink runs and no new external output is configured.
- [ ] TUI sink behavior remains unchanged apart from encrypted marker storage.
