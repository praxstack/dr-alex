"""App tests: it imports/constructs, RED short-circuits the LLM, F1 shows the card."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from textual.widgets import Input, Static

from dr_alex import app as app_module
from dr_alex.app import CrisisScreen, DrAlexApp
from safety.triage import Tier


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


def test_green_turn_goes_through_run_turn(monkeypatch) -> None:
    """D1: the TUI must route GREEN/AMBER through the ONE shared engine.run_turn pipeline,
    not a divergent copy of the safety sequence."""
    calls = {"n": 0}
    real_run_turn = app_module.engine.run_turn

    def spy(*a, **k):
        calls["n"] += 1
        assert "generate_fn" in k  # the TUI injects its streaming hook into the shared pipeline
        return real_run_turn(*a, **k)

    monkeypatch.setattr(app_module.engine, "run_turn", spy)
    monkeypatch.setattr(
        app_module.llm, "stream",
        lambda *a, **k: iter(["all good here."]),
    )

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "made progress on housing today"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert calls["n"] == 1

    asyncio.run(drive())


def test_red_turn_persists_through_run_turn(monkeypatch) -> None:
    """D1: RED persistence is owned by run_turn (single pipeline), not an inline copy."""
    calls = {"n": 0}
    real_run_turn = app_module.engine.run_turn

    def spy(*a, **k):
        calls["n"] += 1
        return real_run_turn(*a, **k)

    monkeypatch.setattr(app_module.engine, "run_turn", spy)

    async def drive() -> None:
        app = DrAlexApp()
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "I want to kill myself"
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            crisis_text = _all_text(app, ".msg-crisis")
            assert "14416" in crisis_text
        assert calls["n"] == 1  # RED still short-circuits inside run_turn (no model call)

    asyncio.run(drive())


def test_alexd_turn_goes_through_run_turn(monkeypatch) -> None:
    """D1: the alexd/phone surface routes every turn through the SAME run_turn."""
    from dr_alex import alexd

    called = {"n": 0}
    monkeypatch.setattr(
        alexd.engine, "run_turn",
        lambda *a, **k: engine_stub(),
    )

    class _Out:
        tier = Tier.GREEN
        text = "hi"
        safety_action = "none"
        chunk_ids: list = []
        memory_ids: list = []

    def engine_stub():
        called["n"] += 1
        return _Out()

    sess = alexd.RoomSession("s1", test_traffic=True)
    alexd._run_turn_blocking(sess, "hello there")
    assert called["n"] == 1


def test_checkin_mode_opener() -> None:
    async def drive() -> None:
        app = DrAlexApp(mode="checkin")
        async with app.run_test() as pilot:
            await pilot.pause()
            text = _all_text(app, ".msg-alex")
            assert "today" in text.lower()

    asyncio.run(drive())
