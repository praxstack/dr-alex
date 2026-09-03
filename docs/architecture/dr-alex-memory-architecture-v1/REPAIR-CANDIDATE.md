# Parent repair candidate

**Status:** non-normative draft pending all reviewer outputs

## D1 smallest safe repair

Reuse existing Dr. Alex components only:

- paired-device ID as the authenticated local subject;
- `dr_alex.crypto` for all body-bearing fields;
- existing `state.db`, not a new database;
- existing `engine.run_turn` and `record_turn_telemetry` as the single persistence seam;
- existing `fanout.finalize_session` step functions, not a second fan-out;
- an existing/default-off runtime configuration gate.

Replace the global plaintext `UnfinalizedMarker` with a `finalization_operations` table keyed by `session_id`. Encrypt its distilled payload. Persist per-step receipts and deterministic destination IDs. A duplicate end request returns the existing operation receipt. Overlapping sessions never overwrite each other.

Resolve paired-device principal and effective consent before startup recovery, memory assembly, turn persistence, or finalization. A denied transcript-retention grant still writes body-free safety telemetry but no transcript rows. Durable memory must either require transcript retention or retain a minimal encrypted provenance event that has its own consent and deletion semantics. The final spec must choose one.

Bind every PWA session to the verified paired-device principal. Every later start, turn, end, status, export, correction, withdrawal, or deletion request must present the same principal.

## M1 required boundary

Do not treat `--client NAME` as authentication. A clinical service needs a non-self-asserted runtime identity and an encrypted root whose key is unavailable to the general Hermes process. A dedicated local service identity plus a permissioned Unix socket is the current strongest implementable option. No live service user, root, key, or launch configuration may be created in this run without the human gate.

M1 code may implement and test the protocol against synthetic temporary users/credentials only after the architecture pins:

- peer authentication;
- key owner and storage;
- encrypted artifact set;
- decryption failure behavior;
- rotation;
- backup and restore;
- deletion and erasure manifests.

## H1 hook correction

Keep the existing Hermes finalize hook body-free. It supplies `session_id`, platform, and reason, not a transcript. The disabled adapter must read a committed session by ID through a narrow profile-aware session-store API after consent authorization. If no stable API exists, add that reader as a named prerequisite. Do not add transcript bodies to hook payloads.

## Candidate eight-commit ceiling

The final ticket graph should use no more than eight implementation commits:

1. D1 device-bound consent and consent-aware transcript persistence.
2. D1 encrypted per-session finalization operations and lifecycle wiring.
3. D1 inspect, correct, export, withdrawal, deletion, and no-activation proof.
4. M1 authenticated clinical service protocol.
5. M1 encrypted clinical root, deletion, backup, and restore acceptance.
6. H1 profile-aware committed-session reader plus disabled adapter.
7. H1 synthetic cross-surface parity harness.
8. Final conformance repair only if a material review defect remains. Otherwise unused.
