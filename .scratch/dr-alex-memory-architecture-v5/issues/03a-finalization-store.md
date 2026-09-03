# Ticket 03A: Close sessions into body-free terminal receipts

**What to build:** End-to-end finalization for outcomes that must never carry a replay payload or call a sink: no retention, RED, no durable-memory grant, and writer disabled.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Existing databases migrate transactionally and idempotently to the exact `finalization_operations` schema; policy storage works with telemetry disabled.
- [ ] PWA End re-resolves consent before finalization and stores one body-free terminal row with the correct lifecycle status.
- [ ] `closed_transient`, `finalized_no_memory_consent`, `finalized_red_withheld`, and `finalization_disabled` rows have NULL payload and lease fields.
- [ ] Duplicate End returns the same operation/receipt without recreating a live session.
- [ ] Default configuration creates no operation row and preserves existing behavior.
- [ ] D1-F01..F04, D1-F07, D1-F08, RC4-R01, RC4-R03, RC4-R07, RC4-R08 pass.
