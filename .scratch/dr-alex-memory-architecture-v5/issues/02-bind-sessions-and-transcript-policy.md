# 02: Bind PWA sessions and transcript writes to current policy

**What to build:** Bind each PWA session to its verified device actor and make the existing shared turn path write transcript bodies only when the explicit current policy permits it. Keep safety telemetry body-free and preserve legacy callers.

**Blocked by:** 01: Establish local identity and consent receipts.

**Status:** ready-for-agent

- [ ] `D1-I04`, `D1-I06`, `D1-I07`, and `D1-I08` pass for owner checks and session creation rules.
- [ ] `D1-T01` through `D1-T07` pass for retain, deny, RED, failure, and pending-fragment behavior.
- [ ] Missing or cross-device sessions remain externally indistinguishable 404 responses.
- [ ] Existing TUI and one-shot behavior remain unchanged.
