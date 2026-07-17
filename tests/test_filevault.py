"""FileVault startup check: parse on/off/unknown; warn only on a positive OFF (D2)."""

from __future__ import annotations

import subprocess

from dr_alex import filevault


def _fake_proc(out: str):
    return subprocess.CompletedProcess(args=["fdesetup", "status"], returncode=0, stdout=out, stderr="")


def test_on(monkeypatch) -> None:
    monkeypatch.setattr(filevault, "_run_fdesetup", lambda: _fake_proc("FileVault is On."))
    st = filevault.status()
    assert st.on is True
    assert filevault.warning_banner(st) is None


def test_off_warns_loudly(monkeypatch) -> None:
    monkeypatch.setattr(filevault, "_run_fdesetup", lambda: _fake_proc("FileVault is Off."))
    st = filevault.status()
    assert st.on is False
    banner = filevault.warning_banner(st)
    assert banner is not None and "FileVault is OFF" in banner


def test_unknown_does_not_warn(monkeypatch) -> None:
    monkeypatch.setattr(filevault, "_run_fdesetup", lambda: _fake_proc("something weird"))
    st = filevault.status()
    assert st.on is None
    assert st.should_warn is False


def test_spawn_failure_is_unknown(monkeypatch) -> None:
    def boom():
        raise OSError("no fdesetup")

    monkeypatch.setattr(filevault, "_run_fdesetup", boom)
    st = filevault.status()
    assert st.on is None
    assert filevault.warning_banner(st) is None
