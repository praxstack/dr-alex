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
