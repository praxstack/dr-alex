"""The Dr. Alex Morgan TUI — a warm, calm full-screen chat.

Design intent: soft palette (never neon), generous spacing, a gentle persona header, an
always-visible "Feeling unsafe? press F1 for help" bar, and — above all — safety-first
turn handling. STEP 0 of every turn is deterministic triage; a RED verdict renders the
pure crisis card and never calls the LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Center, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from dr_alex import (
    engine,
    fanout,
    filevault,
    llm,
    memstore,
    statedb,
    statefile,
    telemetry,
)
from dr_alex.session import SessionState
from dr_alex.widgets import HomeworkScreen, MoodBar, rail_data, render_rail
from safety import crisis_card
from safety.triage import Tier


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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

    #topbar {
        dock: top;
        height: auto;
    }

    #header {
        height: 3;
        padding: 1 3 0 3;
        color: #c9bdf0;
        background: #232839;
    }

    #fv-banner {
        display: none;
        height: auto;
        padding: 0 3;
        color: #2a2030;
        background: #d9a86a;
        text-style: bold;
    }
    #fv-banner.on {
        display: block;
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

    #bottombar {
        dock: bottom;
        height: auto;
        background: #232839;
    }

    #prompt {
        margin: 0 2 0 2;
        border: round #4a5170;
        background: #232839;
        color: #e7e7ee;
    }
    #prompt:focus {
        border: round #a99be0;
    }

    #helpbar {
        height: 1;
        padding: 0 3;
        color: #d9a86a;
        background: #232839;
        content-align: left middle;
    }

    #voice-indicator {
        display: none;
        height: 1;
        padding: 0 3;
        color: #2a2030;
        background: #d98a8a;
        text-style: bold;
        content-align: left middle;
    }
    #voice-indicator.on {
        display: block;
    }

    #rail {
        dock: right;
        width: 28;
        padding: 1 2;
        color: #c9bdf0;
        background: #232839;
    }

    MoodBar {
        height: 3;
        padding: 0 2;
        background: #232839;
        align: left middle;
    }
    .mood-label {
        color: #9aa0b5;
        padding: 1 1 0 0;
        width: auto;
    }
    .mood-chip {
        min-width: 4;
        margin: 0 0 0 1;
    }

    #hw-box {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 2 3;
        border: round #6fae9f;
        background: #232839;
    }
    .hw-row { height: auto; margin: 1 0; }
    .hw-done { min-width: 8; margin-right: 2; }
    .hw-item { padding: 1 0; }
    HomeworkScreen { align: center middle; background: #1c2030 80%; }

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
        ("f2", "homework", "Homework"),
        ("f3", "voice", "Voice"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, mode: str = "full") -> None:
        super().__init__()
        self.mode = mode
        self._history: list[llm.Message] = []
        self._recent_risk: Tier | None = None
        self._session = SessionState()
        self._system_prompt = engine.system_prompt()
        # Phase 3 session bookkeeping (drives the end-of-session fan-out + G5/G8).
        self._session_id = _iso_now().replace(":", "").replace("-", "")
        self._session_started_at = _iso_now()
        self._user_turns = 0
        self._risk_tier_max = Tier.GREEN
        self._finalized = False
        self._explicit_close = False  # set by /bye|/quit|/exit — distinguishes from a stray exit
        # Phase 4 mood: capture "arriving" first, then flip to "leaving" for the close chip.
        self._mood_phase = "open"
        self._test_traffic = telemetry.is_test_traffic()
        # Phase 8 voice press-to-talk: explicit start/stop, visible indicator, no always-on.
        self._recording = False
        self._voice_recorder = None
        self._voice_wav = None

    # -- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="topbar"):
            yield Static(
                f"[b]{PERSONA_TITLE}[/b]  [dim]— {PERSONA_SUBTITLE}[/dim]",
                id="header",
                markup=True,
            )
            # G/D2: a loud, persistent FileVault-off banner (hidden until the check fires).
            yield Static("", id="fv-banner", markup=True)
        yield Static("", id="rail", markup=True)
        yield VerticalScroll(id="chat")
        with Vertical(id="bottombar"):
            yield MoodBar(phase="open")
            yield Static("", id="voice-indicator", markup=True)
            yield Static("Feeling unsafe? press F1 for help  ·  F2 homework  ·  F3 voice", id="helpbar", markup=True)
            yield Input(placeholder="Type to talk to Alex…  (/help  ·  F1 help  ·  F3 voice)", id="prompt")

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
        # G8: a loud staleness banner from cheap state (no subprocess), shown immediately.
        self._show_staleness_banner()
        # D5: if a nightly check-in nudged while the app was closed, show the FIXED next-open
        # banner once, then clear the flag. (No therapy data — the banner is a literal string.)
        self._show_checkin_banner()
        # Phase 4 session start (cheap, local sqlite): record the session, replay the
        # one-time repair-ack, read back open homework, surface any late-night clustering,
        # and paint the right rail. All best-effort — telemetry never breaks a session start.
        self._phase4_startup()
        # FileVault check spawns fdesetup — do it off the UI thread so mount never blocks.
        self._check_filevault()
        # Memory is a session-start READ that shells out to memctl — do it off the UI thread,
        # and only when the store is wired (disabled in tests / degraded environments).
        if memstore.memory_enabled():
            self._start_memory()

    def _phase4_startup(self) -> None:
        try:
            statedb.start_session(self._session_id, is_test_traffic=self._test_traffic)
            # G10: a queued malfunction ack fires here, at a CALM session start — never on a
            # crisis turn (this path runs before any user message).
            ack = telemetry.take_repair_ack()
            if ack:
                self._add_message("alex", escape(ack))
            # Homework read-back ("last time you set X — how did it go?").
            openhw = statedb.open_homework()
            if openhw:
                titles = "; ".join(escape(h.title) for h in openhw[:4])
                self._add_message(
                    "note",
                    f"[b]still open from before:[/b] {titles}  [dim](F2 to mark done)[/dim]",
                )
            # G18: a gentle, data-driven surface if late-night sessions are clustering.
            sig = statedb.late_night_signal()
            if sig.flagged:
                self._add_message(
                    "note",
                    "[dim]I've noticed a few late-night check-ins lately. No judgement — just "
                    "flagging it gently; sleep tends to be load-bearing for how the days feel.[/dim]",
                )
            self._refresh_rail()
        except Exception:  # noqa: BLE001 — startup telemetry is best-effort
            pass

    def _refresh_rail(self) -> None:
        try:
            data = rail_data()
            self.query_one("#rail", Static).update(render_rail(data))
        except Exception:  # noqa: BLE001 — the rail must never break the UI
            pass

    @work(thread=True, group="filevault")
    def _check_filevault(self) -> None:
        try:
            banner = filevault.warning_banner()
        except Exception:  # noqa: BLE001
            banner = None
        if banner:
            self.call_from_thread(self._show_filevault_banner, banner)

    def _show_filevault_banner(self, text: str) -> None:
        """Reveal the persistent, loud FileVault-off banner (non-blocking)."""
        try:
            widget = self.query_one("#fv-banner", Static)
            widget.update(f"⚠ {escape(text)}")
            widget.add_class("on")
        except Exception:  # noqa: BLE001
            pass

    def _show_checkin_banner(self) -> None:
        try:
            from dr_alex import checkin
            banner = checkin.pending_banner()
            if banner:
                self._add_message("note", f"[b]note:[/b] {escape(banner)}")
                checkin.clear_pending()
        except Exception:  # noqa: BLE001 — the banner must never break startup
            pass

    def _show_staleness_banner(self) -> None:
        try:
            from dr_alex import reorient
            state = statefile.load()
            banner = reorient.staleness_banner(
                now=datetime.now(timezone.utc),
                continuity_generated_at=state.continuity_generated_at,
                has_unfinalized=bool(state.unfinalized),
            )
        except Exception:  # noqa: BLE001 — the banner must never break startup
            banner = None
        if banner:
            self._add_message("note", f"[b]note:[/b] {escape(banner)}")

    @work(thread=True, exclusive=True, group="memory")
    def _start_memory(self) -> None:
        """Complete any crashed fan-out, then assemble the once-per-session memory context."""
        try:
            fanout.recover_if_needed()
        except Exception:  # noqa: BLE001 — recovery is best-effort; never block a session
            pass
        try:
            mem = engine.assemble_startup_memory()
            sp = engine.system_prompt_with_memory(mem)
        except Exception:  # noqa: BLE001 — a broken store degrades to the base prompt
            return
        # Fold the immutable memory context into the system prompt for every turn (G20).
        self._system_prompt = sp

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
            self._explicit_close = True
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

    def action_homework(self) -> None:
        """F2 — the homework drawer (list open, mark done)."""
        if not isinstance(self.screen, HomeworkScreen):
            self.push_screen(HomeworkScreen())

    def action_voice(self) -> None:
        """F3 — press-to-talk (council D7). Explicit start/stop, visible indicator, no always-on.

        First press opens the mic (only if a LOCAL transcriber exists); second press stops,
        transcribes locally, and feeds the TEXT into the SAME triage-gated ``process_turn`` as
        typed input (Directive 1). Cloud STT is never an option.
        """
        from dr_alex import voice

        if not self._recording:
            degraded = voice.available()
            if degraded is not None:
                self._add_message("note", f"[dim]{escape(degraded.hint or voice.install_hint())}[/dim]")
                return
            try:
                self._voice_recorder = voice.FfmpegRecorder()
                self._voice_wav = voice.begin_capture(self._voice_recorder)
            except Exception:  # noqa: BLE001 — a mic failure degrades to text, never crashes
                self._add_message("note", "[dim]Couldn't open the mic — just type instead.[/dim]")
                self._voice_recorder = None
                self._voice_wav = None
                return
            self._recording = True
            self._set_voice_indicator("[b]● REC[/b]  listening — press F3 to stop")
        else:
            # Stop + transcribe off the UI thread (whisper can block); indicator → "transcribing".
            self._recording = False
            self._set_voice_indicator("[b]…[/b] transcribing")
            self._finish_voice()

    def _set_voice_indicator(self, markup_text: str | None) -> None:
        try:
            widget = self.query_one("#voice-indicator", Static)
            if markup_text:
                widget.update(markup_text)
                widget.add_class("on")
            else:
                widget.remove_class("on")
        except Exception:  # noqa: BLE001
            pass

    @work(thread=True, exclusive=True, group="voice")
    def _finish_voice(self) -> None:
        from dr_alex import voice

        recorder, wav = self._voice_recorder, self._voice_wav
        self._voice_recorder = None
        self._voice_wav = None
        text = ""
        try:
            if recorder is not None and wav is not None:
                res = voice.finish_capture(recorder, wav)
                text = res.text if not res.degraded else ""
        except Exception:  # noqa: BLE001 — transcription must never crash the app
            text = ""
        self.call_from_thread(self._set_voice_indicator, None)
        self.call_from_thread(self._deliver_voice_text, text)

    def _deliver_voice_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self._add_message("note", "[dim]Didn't catch that — try again, or just type.[/dim]")
            return
        # Route EXACTLY like typed input: show it, then the single triage-gated turn.
        self._add_message("user", escape(text))
        self.process_turn(text)

    def on_mood_bar_picked(self, event: MoodBar.Picked) -> None:
        """Record a mood chip (open, then close) — always skippable, never blocking."""
        phase = self._mood_phase
        if event.value is not None:
            try:
                statedb.record_mood(phase, event.value, session_id=self._session_id)
            except Exception:  # noqa: BLE001
                pass
            self._add_message("note", f"[dim]mood noted — {event.value}/10. thanks for marking it.[/dim]")
            self._refresh_rail()
        # After the "arriving" chip (chosen or skipped), flip the bar to the "leaving" chip.
        if phase == "open":
            self._mood_phase = "close"
            try:
                self.query_one(MoodBar).phase = "close"
                self.query_one(".mood-label", Label).update("And how are you leaving things? (1–10)")
            except Exception:  # noqa: BLE001
                pass

    # -- the safety-first turn --------------------------------------------

    def process_turn(self, text: str) -> None:
        """STEP 0: triage FIRST. RED short-circuits before any model call.

        The whole turn pipeline (triage → retrieve → model → gates → the G1 re-ask
        backstop → telemetry) lives in ONE place — :func:`engine.run_turn` (D1). This
        surface only owns its threaded/streaming render; it never re-implements the safety
        sequence. ``prev_risk`` is captured BEFORE it is overwritten so ``run_turn`` re-runs
        triage with the exact same recent-risk memory this surface used.
        """
        prev_risk = self._recent_risk
        tier = engine.classify(text, recent_risk=prev_risk, now=datetime.now())
        self._recent_risk = tier
        self._user_turns += 1
        if _TIER_RANK[tier] > _TIER_RANK[self._risk_tier_max]:
            self._risk_tier_max = tier

        if tier is Tier.RED:
            # Hard gate: render the pure crisis card + grounding. No LLM. Persistence of the
            # RED turn (trace + encrypted transcript) runs through the SAME run_turn pipeline
            # every surface shares — no divergent inline telemetry copy (D1). run_turn's RED
            # path mints no capability token and never reaches retrieval or the model.
            self._add_message("crisis", engine.red_response_rich(text))
            self._add_message(
                "note",
                "[b]Reach Shreya.[/b] A message you could send her (you send it, not me):\n"
                f'[i]"{escape(crisis_card.SHREYA_REACH_OUT_DRAFT)}"[/i]',
            )
            engine.run_turn(
                text, recent_risk=prev_risk, session=self._session,
                session_id=self._session_id, system_prompt_override=self._system_prompt,
            )
            return

        # GREEN / AMBER -> run the ONE shared pipeline in a worker, streaming the render.
        self._history.append(llm.Message(role="user", content=text))
        widget = self._add_message("alex", "[dim]…[/dim]")
        self._reply(tier, widget, text, prev_risk)

    @work(thread=True, exclusive=True, group="llm")
    def _reply(self, tier: Tier, widget: Static, user_text: str, prev_risk: Tier | None) -> None:
        """Threaded GREEN/AMBER render — delegates the entire safety pipeline to run_turn.

        The TUI's only divergence from the CLI/alexd path is a streaming model call; it is
        injected as ``generate_fn`` so retrieval, the G1 re-ask backstop, the deterministic
        output gates, the trace, and telemetry all run in engine.run_turn (D1). The gates
        still need the whole reply, so the stream is buffered before gating — identical
        semantics to the shared entrypoint, just wired through ``llm.stream`` for the render.
        """
        def _stream_generate(messages, gen_tier, **kwargs):
            text = "".join(llm.stream(messages, gen_tier, **kwargs)).strip()
            return llm.LLMResult(ok=bool(text), text=text or "(no response)", tier=gen_tier)

        out = engine.run_turn(
            user_text,
            history=list(self._history[:-1]),  # run_turn re-appends the current user turn
            recent_risk=prev_risk,
            session=self._session,
            session_id=self._session_id,
            system_prompt_override=self._system_prompt,
            generate_fn=_stream_generate,
        )
        reply = out.text or "(no response)"
        self._history.append(llm.Message(role="assistant", content=reply))
        self.call_from_thread(widget.update, "[b]Alex[/b]\n" + escape(reply))
        self.call_from_thread(self._scroll_chat)

    def _scroll_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    # -- session-end fan-out (Channels B + C) -----------------------------

    def on_unmount(self) -> None:
        """On TUI exit, fan the session out to durable memory (idempotent, best-effort).

        Only when the store is wired AND a real conversation happened. A '/bye' is an
        explicit close; an incidental exit needs > 2 user turns. Never raises on the way out.
        """
        # Phase 4: stamp the session's end (drives streaks + the late-night monitor). Runs
        # independently of the memory store and is best-effort.
        try:
            statedb.end_session(self._session_id)
        except Exception:  # noqa: BLE001
            pass
        if self._finalized or not memstore.memory_enabled():
            return
        if not fanout.should_finalize(self._user_turns, explicit_close=self._explicit_close):
            return
        self._finalized = True
        turns = [(m.role, m.content) for m in self._history]
        try:
            fanout.finalize_session(
                turns,
                session_id=self._session_id,
                started_at=self._session_started_at,
                risk_tier_max=self._risk_tier_max.value,
            )
        except Exception:  # noqa: BLE001 — session end must never crash on the way out
            pass


_TIER_RANK = {Tier.GREEN: 0, Tier.AMBER: 1, Tier.RED: 2}


def run(mode: str = "full") -> None:
    DrAlexApp(mode=mode).run()
