"""Phase-4 Textual widgets: the mood chips, the homework drawer, and the right-rail render.

Design constraints that keep these safe to drop into the existing warm TUI:
  - **Never steal focus** from the message input. The mood bar is a docked strip of buttons;
    the input keeps focus so typing (and the safety-first turn) is never intercepted.
  - **Keyboard-navigable + skippable** (item 3): the mood buttons are Tab/Enter reachable and
    there is an explicit Skip.
  - The right rail (item 6) is a pure render of the 30-day mood sparkline + the gentle,
    breakable cadence line — no logic, no pressure copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from dr_alex import sparkline as _sparkline
from dr_alex import statedb, streaks

# ---------------------------------------------------------------------------
# Mood chips (item 3) — a docked, non-focus-stealing 1–10 + Skip strip.
# ---------------------------------------------------------------------------


class MoodBar(Horizontal):
    """A compact mood-capture strip. Emits :class:`MoodBar.Picked` on a choice or skip."""

    class Picked(Message):
        def __init__(self, value: int | None, phase: str) -> None:
            self.value = value
            self.phase = phase
            super().__init__()

    def __init__(self, phase: str = "open", **kwargs) -> None:
        super().__init__(**kwargs)
        self.phase = phase

    def compose(self) -> ComposeResult:
        label = "How are you arriving? (1 low – 10 good)" if self.phase == "open" \
            else "And how are you leaving things? (1–10)"
        yield Label(label, classes="mood-label")
        for i in range(1, 11):
            yield Button(str(i), id=f"mood-{i}", classes="mood-chip")
        yield Button("Skip", id="mood-skip", classes="mood-chip mood-skip")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        value: int | None = None
        if bid.startswith("mood-") and bid != "mood-skip":
            try:
                value = int(bid.split("-", 1)[1])
            except ValueError:
                value = None
        self.post_message(self.Picked(value, self.phase))


# ---------------------------------------------------------------------------
# Homework drawer (item 4) — list open homework, mark done.
# ---------------------------------------------------------------------------


class HomeworkScreen(ModalScreen[None]):
    """A drawer over the chat listing OPEN homework; each item can be marked done."""

    BINDINGS = [("escape", "dismiss", "Close"), ("f2", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, db_path=None) -> None:
        super().__init__()
        self._db_path = db_path

    def compose(self) -> ComposeResult:
        with Center(), VerticalScroll(id="hw-box"):
            yield Static("[b]Homework[/b]  [dim]— things you set with Shreya / here[/dim]",
                         id="hw-title", markup=True)
            items = statedb.open_homework(path=self._db_path)
            if not items:
                yield Static("[dim]Nothing open right now. That's fine.[/dim]",
                             id="hw-empty", markup=True)
            for hw in items:
                with Horizontal(classes="hw-row"):
                    yield Button("done", id=f"hw-{hw.id}", classes="hw-done")
                    yield Static(escape(hw.title), classes="hw-item", markup=False)
            yield Static("[dim]Press Esc to close.[/dim]", id="hw-hint", markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        if bid.startswith("hw-"):
            statedb.mark_homework_done(bid[3:], path=self._db_path)
            # Simplest reliable refresh: re-open the drawer.
            self.app.pop_screen()
            self.app.push_screen(HomeworkScreen(self._db_path))


# ---------------------------------------------------------------------------
# Right rail (item 6) — 30-day mood sparkline + gentle cadence. Pure render.
# ---------------------------------------------------------------------------


@dataclass
class RailData:
    spark: str
    latest: int | None
    cadence_line: str | None


def rail_data(*, now=None, db_path=None) -> RailData:
    import datetime as _dt

    series = statedb.daily_mood(days=30, now=now, path=db_path)
    spark = _sparkline.sparkline(series, lo=1, hi=10)
    stats = statedb.mood_stats(days=30, now=now, path=db_path)
    today = (now.astimezone(statedb.IST).date() if (now and now.tzinfo)
             else (now.date() if now else _dt.datetime.now(_dt.UTC).astimezone(statedb.IST).date()))
    cad = streaks.compute(statedb.checkin_dates(path=db_path), today=today)
    return RailData(spark=spark, latest=stats.latest, cadence_line=streaks.gentle_line(cad))


def render_rail(data: RailData) -> str:
    lines = ["[b]last 30 days[/b]", "", f"[#a99be0]{data.spark or ' '}[/#a99be0]"]
    if data.latest is not None:
        lines.append(f"[dim]latest mood {data.latest}/10[/dim]")
    else:
        lines.append("[dim]no mood yet[/dim]")
    if data.cadence_line:
        lines += ["", f"[dim]{escape(data.cadence_line)}[/dim]"]
    return "\n".join(lines)
