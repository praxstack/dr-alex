"""Test hermeticity for Dr. Alex.

Phase 3 wires Dr. Alex to the real memory store + the model. To keep the suite fast,
offline, and — above all — incapable of touching the live ``~/agent-memory`` store or the
live continuity brief, memory is DISABLED by default for every test (``DR_ALEX_MEMORY_OFF``).
Tests that exercise the memory path opt back in explicitly and point the bridge at a
throwaway store (see ``test_memctl_recall_smoke`` / ``test_memory_integration``).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _memory_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Belt-and-suspenders: the whole suite runs as if the store were unwired unless a test
    # deliberately turns memory on. This prevents the TUI's session-start recall and
    # session-end fan-out from ever spawning memctl / claude against the LIVE store.
    monkeypatch.setenv("DR_ALEX_MEMORY_OFF", "1")
