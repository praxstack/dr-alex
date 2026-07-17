"""Phase-4 TUI wiring: mood chips, homework drawer, and the G10 repair-ack at session start."""

from __future__ import annotations

import asyncio

from textual.widgets import Button, Static

from dr_alex import statedb, telemetry
from dr_alex.app import DrAlexApp
from dr_alex.widgets import HomeworkScreen

# A wide test viewport so the 1–10 mood strip lays out fully (clicks need real geometry).
_WIDE = (140, 40)


def _all_text(node, selector: str) -> str:
    return "\n".join(str(w.render()) for w in node.query(selector).results(Static))


def test_mood_chip_records_open_mood() -> None:
    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            await pilot.click("#mood-7")
            await pilot.pause()
        # The open-mood chip landed in state.db.
        stats = statedb.mood_stats()
        assert stats.latest == 7

    asyncio.run(drive())


def test_mood_bar_flips_to_close_phase() -> None:
    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            assert app._mood_phase == "open"
            await pilot.click("#mood-6")   # arriving
            await pilot.pause()
            assert app._mood_phase == "close"
            await pilot.click("#mood-8")   # leaving
            await pilot.pause()
        # Two chips recorded: open=6, then close=8 (latest).
        assert statedb.mood_stats().points == 2
        assert statedb.mood_stats().latest == 8

    asyncio.run(drive())


def test_homework_drawer_lists_and_marks_done() -> None:
    statedb.add_homework("SEED_HW_walk_before_standup")
    hid = statedb.open_homework()[0].id

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            # Session start reads back open homework.
            assert "SEED_HW_walk_before_standup" in _all_text(app, ".msg-note")
            await pilot.press("f2")
            await pilot.pause()
            assert isinstance(app.screen, HomeworkScreen)
            # Modal content lives on the pushed screen.
            assert "SEED_HW_walk_before_standup" in _all_text(app.screen, ".hw-item")
            await pilot.click(app.screen.query_one(f"#hw-{hid}", Button))
            await pilot.pause()

    asyncio.run(drive())
    assert statedb.open_homework() == []
    assert statedb.all_homework()[0].status == "done"


def test_repair_ack_fires_at_session_start_not_on_crisis(monkeypatch) -> None:
    from dr_alex import app as app_module
    from textual.widgets import Input

    # A prior malfunction was flagged; the ack should surface at the CALM opener.
    telemetry.note_malfunction("empty_reply")

    # Spy on the ack: it may fire ONCE at startup, and must NEVER fire during a crisis turn.
    calls = {"n": 0}
    real = app_module.telemetry.take_repair_ack

    def spy(**kwargs):
        calls["n"] += 1
        return real(**kwargs)

    monkeypatch.setattr(app_module.telemetry, "take_repair_ack", spy)

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            assert calls["n"] == 1  # fired once, at the calm session start
            alex_text = _all_text(app, ".msg-alex")
            assert "blank reply" in alex_text  # the empty_reply ack copy
            # Now a RED (crisis) turn — the ack machinery must NOT fire again here.
            app.query_one("#prompt", Input).value = "I want to kill myself"
            await pilot.press("enter")
            await pilot.pause()
            assert calls["n"] == 1  # unchanged — never on a crisis turn
        # Fires exactly once total — nothing pending afterwards.
        assert statedb.pending_repair_ack() is None

    asyncio.run(drive())


def test_filevault_off_shows_persistent_banner(monkeypatch) -> None:
    from dr_alex import app as app_module

    monkeypatch.setattr(app_module.filevault, "warning_banner", lambda *a, **k: "FileVault is OFF — turn it on.")

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test(size=_WIDE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            banner = app.query_one("#fv-banner", Static)
            assert banner.has_class("on")
            assert "FileVault is OFF" in str(banner.render())

    asyncio.run(drive())


def test_right_rail_renders_mood_sparkline() -> None:
    statedb.record_mood("open", 5)

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            rail = str(app.query_one("#rail", Static).render())
            assert "last 30 days" in rail

    asyncio.run(drive())
