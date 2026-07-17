"""App tests: it imports/constructs, RED short-circuits the LLM, F1 shows the card."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from textual.widgets import Input, Static

from dr_alex import app as app_module
from dr_alex.app import CrisisScreen, DrAlexApp


def _all_text(app: DrAlexApp, selector: str) -> str:
    return "\n".join(str(w.render()) for w in app.query(selector).results(Static))


def test_app_constructs() -> None:
    # Construction reads persona + continuity and assembles the system prompt.
    app = DrAlexApp()
    assert app.mode == "full"
    assert app._system_prompt
    assert "Dr. Alex" in app._system_prompt or "Alex Morgan" in app._system_prompt


def test_green_turn_streams_reply(monkeypatch) -> None:
    stream_mock = MagicMock(side_effect=lambda *a, **k: iter(["Hey Prax. ", "I'm right here."]))
    monkeypatch.setattr(app_module.llm, "stream", stream_mock)

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "had an okay day, tried a 30 min block"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = _all_text(app, ".msg-alex")
            assert "I'm right here." in text
        assert stream_mock.called

    asyncio.run(drive())


def test_red_turn_short_circuits_llm(monkeypatch) -> None:
    stream_mock = MagicMock()
    monkeypatch.setattr(app_module.llm, "stream", stream_mock)

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "I want to kill myself"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            # The LLM must NOT have been called on a RED turn.
            assert stream_mock.call_count == 0
            # The pure crisis card was rendered instead.
            crisis_text = _all_text(app, ".msg-crisis")
            assert "14416" in crisis_text
            # And a 'reach Shreya' note is offered.
            note_text = _all_text(app, ".msg-note")
            assert "Shreya" in note_text

    asyncio.run(drive())


def test_f1_shows_crisis_screen() -> None:
    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            await pilot.press("f1")
            await pilot.pause()
            assert isinstance(app.screen, CrisisScreen)
            card = str(app.screen.query_one("#crisis-card", Static).render())
            assert "14416" in card
            assert "Shreya" in card

    asyncio.run(drive())


def test_panic_command_shows_crisis_screen() -> None:
    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "/panic"
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, CrisisScreen)

    asyncio.run(drive())


def test_checkin_mode_opener() -> None:
    async def drive() -> None:
        app = DrAlexApp(mode="checkin")
        async with app.run_test() as pilot:
            await pilot.pause()
            text = _all_text(app, ".msg-alex")
            assert "today" in text.lower()

    asyncio.run(drive())
