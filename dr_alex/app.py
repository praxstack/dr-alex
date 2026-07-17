"""The Dr. Alex Morgan TUI — a warm, calm full-screen chat.

Design intent: soft palette (never neon), generous spacing, a gentle persona header, an
always-visible "Feeling unsafe? press F1 for help" bar, and — above all — safety-first
turn handling. STEP 0 of every turn is deterministic triage; a RED verdict renders the
pure crisis card and never calls the LLM.
"""

from __future__ import annotations

from datetime import datetime

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Center, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from dr_alex import engine, llm
from safety import crisis_card
from safety.triage import Tier

PERSONA_TITLE = "Dr. Alex Morgan"
PERSONA_SUBTITLE = "support between your sessions with Shreya"

HELP_TEXT = (
    "[b]A few ways to steer:[/b]\n"
    "  [b]/help[/b]   — this note\n"
    "  [b]/panic[/b]  — the crisis card (same as F1)\n"
    "  [b]/bye[/b]    — end for now\n\n"
    "Press [b]F1[/b] any time to see help resources. Just type to talk — plain words are "
    "all you need. I'm here as support between your sessions with Shreya, not a "
    "replacement for her or a clinician."
)


class CrisisScreen(ModalScreen[None]):
    """Pure crisis card. No LLM. Reachable via F1 or /panic."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("f1", "dismiss", "Back"),
        ("q", "dismiss", "Back"),
    ]

    def compose(self) -> ComposeResult:
        with Center():
            with VerticalScroll(id="crisis-box"):
                yield Static(crisis_card.render_rich(), id="crisis-card", markup=True)
                yield Static(
                    "[dim]Press Esc to come back. I'm still here.[/dim]",
                    id="crisis-hint",
                    markup=True,
                )


class DrAlexApp(App[None]):
    TITLE = "Dr. Alex Morgan"
    SUB_TITLE = "support between your sessions with Shreya"

    CSS = """
    Screen {
        background: #1c2030;
        color: #e7e7ee;
        layers: base;
    }

    #header {
        dock: top;
        height: 3;
        padding: 1 3 0 3;
        color: #c9bdf0;
        background: #232839;
    }

    #chat {
        padding: 1 3;
        background: #1c2030;
    }

    .msg {
        margin: 1 0;
        padding: 1 2;
        width: 100%;
    }

    .msg-user {
        color: #cfe8e2;
        border-left: wide #6fae9f;
        background: #212739;
    }

    .msg-alex {
        color: #e7e7ee;
        border-left: wide #a99be0;
        background: #242a3d;
    }

    .msg-crisis {
        color: #f2e7d6;
        border-left: wide #d9a86a;
        background: #2c2a33;
        padding: 1 2;
    }

    .msg-note {
        color: #9aa0b5;
        background: #1c2030;
        padding: 0 2;
    }

    #prompt {
        dock: bottom;
        margin: 0 2 0 2;
        border: round #4a5170;
        background: #232839;
        color: #e7e7ee;
    }
    #prompt:focus {
        border: round #a99be0;
    }

    #helpbar {
        dock: bottom;
        height: 1;
        padding: 0 3;
        color: #d9a86a;
        background: #232839;
        content-align: left middle;
    }

    CrisisScreen {
        align: center middle;
        background: #1c2030 80%;
    }
    #crisis-box {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 2 3;
        border: round #d9a86a;
        background: #2c2a33;
    }
    #crisis-hint {
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("f1", "crisis", "Help"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, mode: str = "full") -> None:
        super().__init__()
        self.mode = mode
        self._history: list[llm.Message] = []
        self._recent_risk: Tier | None = None
        self._system_prompt = engine.system_prompt()

    # -- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(
            f"[b]{PERSONA_TITLE}[/b]  [dim]— {PERSONA_SUBTITLE}[/dim]",
            id="header",
            markup=True,
        )
        yield VerticalScroll(id="chat")
        yield Static("Feeling unsafe? press F1 for help", id="helpbar", markup=True)
        yield Input(placeholder="Type to talk to Alex…  (/help  ·  F1 for help)", id="prompt")

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        if self.mode == "checkin":
            opener = (
                "Hey Prax. Winding down? No agenda — how was today, honestly? "
                "Even a word or two is enough."
            )
        else:
            opener = engine.greeting()
        self._add_message("alex", opener)

    # -- message helpers --------------------------------------------------

    def _add_message(self, kind: str, markup_text: str) -> Static:
        cls = {
            "user": "msg msg-user",
            "alex": "msg msg-alex",
            "crisis": "msg msg-crisis",
            "note": "msg msg-note",
        }.get(kind, "msg")
        prefix = {"user": "[b]You[/b]\n", "alex": "[b]Alex[/b]\n"}.get(kind, "")
        widget = Static(prefix + markup_text, classes=cls, markup=True)
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(widget)
        chat.scroll_end(animate=False)
        return widget

    # -- input handling ---------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if self._handle_command(text):
            return
        self._add_message("user", escape(text))
        self.process_turn(text)

    def _handle_command(self, text: str) -> bool:
        low = text.lower()
        if low in ("/bye", "/quit", "/exit"):
            self.exit()
            return True
        if low == "/help":
            self._add_message("note", HELP_TEXT)
            return True
        if low in ("/panic", "/crisis"):
            self.action_crisis()
            return True
        return False

    def action_crisis(self) -> None:
        # Pure crisis card. No LLM in this path.
        if not isinstance(self.screen, CrisisScreen):
            self.push_screen(CrisisScreen())

    # -- the safety-first turn --------------------------------------------

    def process_turn(self, text: str) -> None:
        """STEP 0: triage FIRST. RED short-circuits before any model call."""
        tier = engine.classify(text, recent_risk=self._recent_risk, now=datetime.now())
        self._recent_risk = tier

        if tier is Tier.RED:
            # Hard gate: render the pure crisis card + grounding. No LLM.
            self._add_message("crisis", engine.red_response_rich())
            self._add_message(
                "note",
                "[b]Reach Shreya.[/b] A message you could send her (you send it, not me):\n"
                f'[i]"{escape(crisis_card.SHREYA_REACH_OUT_DRAFT)}"[/i]',
            )
            return

        # GREEN / AMBER -> call the model in a worker (streams into a widget).
        self._history.append(llm.Message(role="user", content=text))
        widget = self._add_message("alex", "[dim]…[/dim]")
        self._stream_reply(tier, widget)

    @work(thread=True, exclusive=True, group="llm")
    def _stream_reply(self, tier: Tier, widget: Static) -> None:
        messages = list(self._history)
        pieces: list[str] = []
        for chunk in llm.stream(messages, tier, system_prompt=self._system_prompt):
            pieces.append(chunk)
            current = "".join(pieces)
            self.call_from_thread(widget.update, "[b]Alex[/b]\n" + escape(current))
            self.call_from_thread(self._scroll_chat)
        reply = "".join(pieces).strip() or "(no response)"
        self._history.append(llm.Message(role="assistant", content=reply))
        self.call_from_thread(widget.update, "[b]Alex[/b]\n" + escape(reply))
        self.call_from_thread(self._scroll_chat)

    def _scroll_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)


def run(mode: str = "full") -> None:
    DrAlexApp(mode=mode).run()
