# 01: Establish local identity and consent receipts

**What to build:** Give every local Dr. Alex session a server-derived subject, a verified paired-device actor, and explicit consent receipts that remain available when telemetry is disabled. The feature stays default-off and uses synthetic grants only.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `D1-I01` through `D1-I05` pass for verified device identity and stable server-owned subject identity.
- [ ] `D1-C01` through `D1-C15` pass for migration, validation, deny-by-default resolution, expiry, withdrawal, ordering, and telemetry-independent policy state.
- [ ] Room JavaScript contains no consent grant.
- [ ] No live profile, clinical record, route, or configuration changes.
