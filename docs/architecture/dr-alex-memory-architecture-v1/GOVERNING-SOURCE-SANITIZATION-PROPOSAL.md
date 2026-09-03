# Governing source sanitization proposal

**Status:** Approved by the human clinical-governance authority on 2026-08-23; implemented as v3 governing evidence and run contract  
**Decision owner:** Human activation and clinical-governance authority  
**Reason:** The frozen therapist audit contains private clinical excerpts and stale current-state statements. It must not be propagated into prompts, tickets, Git history, or external review packets.

## Requested decision

Approve creation of a new content-free governing evidence set and a new run-contract version. Until approval, RC3 remains review-blocked and no tickets, implementation, migration, activation, deletion, Telegram operation, or live configuration change may proceed.

## Proposed source classes

| Source class | Treatment |
|---|---|
| Original therapist audit | Restricted clinical source. Preserve in place. Do not copy, quote, publish, or send to external reviewers. |
| Original architecture review | Restricted reference. Preserve in place. Use only to derive content-free requirements. |
| Content-free current-state verification | New governing input. Contains only system topology, control status, source locators, hashes, and synthetic acceptance requirements. |
| Source-code and test evidence | Governing implementation evidence at pinned repository commits. No conversation bodies. |
| Review receipts | Stored outside candidate hashes. Findings, verdicts, and evidence locators only. |

## Proposed precedence

1. Human-approved content-free governing requirements.
2. Pinned current source and executable synthetic tests.
3. Current-state addenda when they conflict with older report prose.
4. Original restricted reports as historical context only.

A source-code observation may refine current-state claims. It may not weaken a human-owned clinical safety requirement.

## Content-free governing requirements

1. Current-turn deterministic safety triage runs before retrieval, persistence, distillation, or network-dependent work.
2. Every supported surface executes the same RED classifier and local short-circuit. Human escalation is additive.
3. Message receipt authorizes transient processing only. Transcript retention, durable memory, recall across contexts, and export require explicit scope-specific consent.
4. Non-consented sessions produce no durable body, summary, reusable fact, inbox note, continuity artifact, or external mirror.
5. PWA sessions are bound to authenticated paired-device actors independently of consent.
6. High-sensitivity recall and full-body reads require authenticated runtime authority. Request fields never grant authority.
7. Clinical storage requires a separately encrypted physical boundary and a stronger identity than a process-local client name before activation.
8. Canonical records remain separate from summaries, indexes, embeddings, and graph projections. Derived layers remain rebuildable.
9. User erasure overrides archive-by-default. Clinical data must not remain recoverable from Git history, indexes, WAL, caches, backups, or restore manifests before activation.
10. Real clinical migration and live activation require separate human-approved operations with rollback and non-resurrection evidence.
11. The encrypted standalone PWA remains available until replacement confidentiality, lifecycle, consent, deletion, backup/restore, and response-parity gates pass.
12. Tests and reviews use synthetic content only.

## Scope of the replacement run

The replacement contract should authorize only:

- always-on PWA session ownership;
- default-off, consent-aware transcript policy;
- encrypted legacy marker migration;
- marker-free synthetic finalization tests with no live sink;
- denial of request-flag authority for high-sensitivity recall and full-body access;
- local documentation and test receipts.

It should continue to prohibit:

- clinical-root creation or activation;
- Hermes transcript integration;
- real-data migration;
- deletion or purge of live records;
- Telegram, gateway, cron, credential, key, backup, or profile changes;
- claims of universal continuity or physical isolation.

## Approval effect

Approval does not approve implementation or activation. It only authorizes replacing the sensitive evidence baseline with the content-free set and issuing a new versioned run contract. The new candidate must then receive a fresh independent review against its exact hashes before tickets or code work begin.
