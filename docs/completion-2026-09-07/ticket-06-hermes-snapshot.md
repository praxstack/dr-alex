# Include consistent therapist Hermes history in encrypted recovery generations

## Parent

praxstack/dr-alex#1 D03/D09 and dotfiles#11 M09. The private Dr. Alex archive includes its own data and records; the therapist Hermes database lives elsewhere. Whole-home copies exclude SQLite WAL sidecars and cannot guarantee a consistent raw database copy.

## What to build

Include the existing configured therapist-history database in each encrypted Dr. Alex backup generation, using SQLite's online backup interface. Reuse the current archive, manifest, retention and scheduler; no second history store or backup framework.

## Acceptance criteria

- Resolve the source through the existing therapist-history database configuration. Include only that database, not the profile's credentials or unrelated files.
- With a live WAL-mode synthetic source, the restored archive contains all committed messages, exact Unicode/whitespace, and passes SQLite integrity checking. Do not checkpoint or modify the source.
- The encrypted manifest identifies the source and deterministic archive member. No clinical bodies or secrets appear in logs/receipts.
- Missing optional unconfigured source is reported in coverage; an explicitly configured missing source, corrupt/unreadable source or bounded snapshot failure fails the generation without deleting prior valid generations.
- Snapshot operations have a finite deadline; only validated complete artifacts can report success. Preserve the existing Dr data/record coverage and 14-generation retention.
- Test fixtures redirect all database paths to temporary storage. Full suite and Ruff pass; independent standards/spec review findings are addressed before merge.
- Verify one actual scheduled generation's coverage and isolated restore after deployment. Original-Keychain restore and independent key-kit recovery remain separate evidence.

## Blocked by

Implementation: none. Scheduled live verification: dotfiles#14 deployment. Personal key-loss recovery: dr-alex#5 and the user's independent recipient/storage choice.

## Baseline

Dr. Alex main95a7689. Frozen persona, golden corpus, triage, identity, existing user data and accepted evaluation thresholds stay unchanged. Use owned worktree and explicit-path commits. Candidate-only changes; after two non-improving candidates investigate without weakening acceptance.

## Candidate handoff

Tracked as [Dr. Alex #7](https://github.com/praxstack/dr-alex/issues/7). The archive now resolves the therapist database through `history_recall.db_path()` and includes its validated online snapshot as `hermes/state.db`. It does not scan the rest of that profile. The encrypted recovery manifest adds `coverage.hermes_history`, with `status`, `source`, and `member`. An absent default source records `missing-optional` and a null member; an explicitly configured missing source fails the generation.

The shared `_snapshot_sqlite` helper opens sources read-only, copies in bounded page batches, and validates the result with `PRAGMA integrity_check`. A 30-second monotonic deadline covers backup progress and validation for each database; the existing Dr state and private SQLite paths use the same helper. Empty, unreadable, corrupt and timed-out databases fail before retention can remove a previous generation. The existing 14-generation retention and encrypted archive remain unchanged.

The WAL regression first failed because the archive contained no Hermes member. Synthetic tests now cover committed WAL-only rows with exact Unicode/whitespace, unchanged source main/WAL hashes, omission of adjacent credentials and sidecars, encrypted coverage, missing optional source, explicit missing/corrupt/empty/unreadable/locked source failures, prior-artifact preservation, and a readable database with an invalid index. The global test fixture clears inherited `DR_ALEX_HERMES_DB` and redirects its default to a temporary path; individual history tests explicitly configure synthetic databases.

No real clinical database was backed up or restored for this candidate. A scheduled real generation and isolated restore remain post-review deployment work. Original-Keychain restore and independent key-kit recovery remain separate evidence.

The implementation uses the existing [Python SQLite backup and progress interfaces](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup) and [SQLite online backup API](https://www.sqlite.org/backup.html).
