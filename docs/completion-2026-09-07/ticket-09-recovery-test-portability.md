# Make recovery test dependencies and permission failures portable

Tracking issue: https://github.com/praxstack/dr-alex/issues/10

Parent Dr. Alex #1; post-merge portability repair for PR8 (`eea41b7`). Unit security and
failure tests use a synthetic subprocess boundary when native age is unavailable. One native
age round-trip remains an explicitly skipped integration check when either binary is missing.
The Hermes unreadable-source case injects `PermissionError` only for the configured SQLite
source open, so prior-generation preservation assertions run under privileged readers too.

Baseline receipts: `age-absent-baseline.log` and `privileged-reader-baseline.log`. Final receipts:
`recovery-test-portability-focused-verbose.log`, `recovery-test-portability-age-absent-verbose.log`,
`recovery-test-portability-full.log`, and `recovery-test-portability-ruff.log` in the private
completion directory.

PR12 review found the synthetic age boundary accepted missing or substituted
recipients. It now checks the exact encryption command and the fixture's requested
recipient. Two negative cases failed against the original boundary and pass with
the correction. Production code is unchanged; the native integration still runs.
The final suite passed 706 tests with 3 skips; Ruff passed. Fixture Git commits
use a process-scoped signing override, without changing repository signing policy.

The next review identified another synthetic-boundary gap: it supplied stdout
without requiring capture_output. The boundary now requires captured output and
a bounded timeout, and checks the decryption command shape. Both missing and
false capture flags fail the regression. The final suite passed 708 tests with
3 skips; Ruff passed. Native production encryption/decryption is unchanged.
