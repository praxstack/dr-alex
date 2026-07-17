"""FileVault disk-encryption check (council D2 — the disk layer under app-layer Fernet).

App-layer Fernet protects free-text columns, but the plaintext canonical record
(``records/Active-File.md``, ``data/continuity.md``) and the *structure* of ``state.db`` rely
on full-disk encryption for at-rest protection. So at startup Dr. Alex asks ``fdesetup
status``; if FileVault is OFF it shows a loud, persistent warning banner — but never blocks
(a therapy tool must still open on an unencrypted disk; the warning is the safeguard).

This module owns exactly one subprocess site (``_run_fdesetup``); it never touches the model.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

_log = logging.getLogger("dr_alex.filevault")

_WARNING = (
    "FileVault is OFF — full-disk encryption is not protecting this machine. Your therapy "
    "notes and state.db are only as private as this disk. Turn FileVault on in System "
    "Settings › Privacy & Security › FileVault. (I'll keep working; this is a heads-up.)"
)


@dataclass(frozen=True)
class FileVaultStatus:
    #: True = on, False = off, None = couldn't determine (non-macOS / error).
    on: bool | None
    raw: str = ""

    @property
    def should_warn(self) -> bool:
        """Warn only when we positively determined FileVault is OFF (never on 'unknown')."""
        return self.on is False


def _run_fdesetup() -> subprocess.CompletedProcess[str]:
    """The sole subprocess site here — runs Apple's ``fdesetup status``. Never the model."""
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["/usr/bin/fdesetup", "status"],
        capture_output=True, text=True, timeout=10,
    )


def status() -> FileVaultStatus:
    """Query FileVault, tolerating any failure as 'unknown' (never raises)."""
    try:
        proc = _run_fdesetup()
    except (OSError, subprocess.SubprocessError) as exc:
        _log.info("fdesetup unavailable (%s) — FileVault status unknown", type(exc).__name__)
        return FileVaultStatus(on=None)
    out = (proc.stdout or "").strip()
    low = out.lower()
    if "filevault is on" in low:
        return FileVaultStatus(on=True, raw=out)
    if "filevault is off" in low:
        return FileVaultStatus(on=False, raw=out)
    return FileVaultStatus(on=None, raw=out)


def warning_banner(st: FileVaultStatus | None = None) -> str | None:
    """The loud one-liner when FileVault is off, else None."""
    st = st or status()
    return _WARNING if st.should_warn else None
