"""Test hermeticity for Dr. Alex.

Phase 3 wires Dr. Alex to the real memory store + the model. To keep the suite fast,
offline, and — above all — incapable of touching the live ``~/agent-memory`` store or the
live continuity brief, memory is DISABLED by default for every test (``DR_ALEX_MEMORY_OFF``).
Tests that exercise the memory path opt back in explicitly and point the bridge at a
throwaway store (see ``test_memctl_recall_smoke`` / ``test_memory_integration``).
"""

from __future__ import annotations

import keyring
import keyring.backend
import pytest


class _InMemoryKeyring(keyring.backend.KeyringBackend):
    """A process-local keyring backend for tests.

    Phase 4 stores the state.db Fernet key and the capability-token HMAC key in the macOS
    Keychain. Hitting the real Keychain from the test suite can hang or prompt (especially
    headless), so we install this deterministic in-memory backend for the whole session.
    Encryption/capability round-trips are exercised for real; only the Keychain is faked.
    At RUNTIME the real ``keyring.backends.macOS.Keyring`` backend is used.
    """

    priority = 1  # any positive value; we set it explicitly as the active backend

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


@pytest.fixture(autouse=True, scope="session")
def _fake_keyring() -> None:
    # Install the in-memory backend before any secret is loaded; keep it for the session.
    keyring.set_keyring(_InMemoryKeyring())


@pytest.fixture(autouse=True)
def _memory_off_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Belt-and-suspenders: the whole suite runs as if the store were unwired unless a test
    # deliberately turns memory on. This prevents the TUI's session-start recall and
    # session-end fan-out from ever spawning memctl / claude against the LIVE store.
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "1")
    # Phase 4: every test's state.db lives in a throwaway file, never the real data/state.db.
    monkeypatch.setenv("DR_ALEX_STATE_DB", str(tmp_path / "state.db"))
    # Phase 5: every test's device-pairing db is a throwaway file, never the real
    # data/pairing.db (auth data must never leak into the source tree during a test run).
    monkeypatch.setenv("DR_ALEX_PAIRING_DB", str(tmp_path / "pairing.db"))
    # Phase 6/7: the canonical Active File, records dir, and exports dir all point at throwaway
    # paths so no test ever writes clinical content into the repo's records/ or exports/.
    monkeypatch.setenv("DR_ALEX_RECORDS_DIR", str(tmp_path / "records"))
    monkeypatch.setenv("DR_ALEX_ACTIVE_FILE", str(tmp_path / "records" / "Active-File.md"))
    monkeypatch.setenv("DR_ALEX_EXPORTS_DIR", str(tmp_path / "exports"))
    # Phase 7: the nightly check-in's pending-flag file lives in a throwaway path.
    monkeypatch.setenv("DR_ALEX_CHECKIN_STATE", str(tmp_path / "checkin.json"))
    # Phase 6: the Notion mirror is OFF by default in the suite (belt-and-suspenders) so no
    # test can ever reach the real Notion API. Tests that exercise the mirror opt back in and
    # inject an httpx.MockTransport client.
    monkeypatch.setenv("DR_ALEX_NOTION_OFF", "1")
