# ADR-0001: Repair existing memory exposure before adding PWA retention

**Status:** Accepted decision candidate; implementation authority begins only with the exact-hash approval receipt  
**Date:** 2026-08-23

## Context

The standalone PWA does not execute the TUI's durable fan-out. Existing fan-out writes several
sensitive derived sinks and relies on one global crash marker. The browser also lacks a reliable
normal close transition. The content-free requirements derived under the current user instruction
require purpose-specific retention consent, deletion, backup/restore, and confidentiality gates
before expanding retention; the restricted reports remain historical provenance.

Two independent existing defects do not require that product decision: the TUI crash digest is
plaintext at rest, and agent-memory's legacy `include_sensitive` request bypasses its existing
high-sensitivity authorization.

## Decision

Implement only the two independent security repairs in v3. Do not add PWA durable fan-out,
consent infrastructure, identity infrastructure, or synthetic lifecycle machinery.

PWA lifecycle work requires a new human-approved policy and evaluator covering consent copy,
retention, withdrawal/deletion propagation, permitted sinks, RED handling, close/retry/restart
semantics, backups, rollback, and activation.

## Consequences

- Existing exposure is reduced with small, testable diffs.
- Current normal/non-conflicting TUI, PWA, CLI trust-path, Hermes, and live sink behavior stays
  unchanged; a conflicting TUI session fails closed before any sink, and non-allowlisted
  agent-memory callers lose the legacy bypass by design.
- The PWA lifecycle gap remains visible and intentionally blocked.
- Existing TUI retention remains an unresolved human policy decision, not a compliance claim.
- Physical clinical isolation remains unimplemented and must not be claimed.
- v2 rc3's dormant tables, leases, flags, and synthetic runner are rejected for this run.

## Revisit when

A human-owned retention policy and user experience are approved, and a fixed synthetic evaluator
covers abandoned tabs, duplicate close, overlap, crash recovery, deletion, backup, and restore.
