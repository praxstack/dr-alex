# Ticket 03C: Recover safely under failure and concurrency

**What to build:** Interrupted and concurrent synthetic finalization converges on one operation without duplicate or stale-worker sink writes.

**Blocked by:** 03B

**Status:** ready-for-agent

- [ ] Partial synthetic failure returns HTTP 202 (`ok=false`, `complete=false`) and stores `recovery_pending` with encrypted payload and class-only error.
- [ ] Duplicate pending End claims one expired/released lease and resumes only unfinished deterministic steps.
- [ ] Two first End requests create one row; exactly one owns generation 1; loser calls no sink.
- [ ] Lease takeover increments generation; every renewal, step, error, erase, and completion is owner+generation fenced; stale worker writes nothing.
- [ ] Consent is re-resolved before claim and before every step; withdrawal erases payload and stops unfinished sinks.
- [ ] Overlapping sessions retain separate rows and payloads.
- [ ] D1-F06, D1-F10, D1-F12..F14 and RC4-R02, RC4-R04, RC4-R05 pass.
