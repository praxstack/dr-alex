"""Press-to-talk voice (council D7): fake transcriber, ephemeral audio, local-only, no bypass."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from dr_alex import voice

_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fakes — the suite NEVER spawns ffmpeg or whisper
# ---------------------------------------------------------------------------


class _FakeRecorder:
    def __init__(self, transcript_bytes: bytes = b"RIFF....fake wav") -> None:
        self.started = False
        self.stopped = False
        self._path: Path | None = None
        self._bytes = transcript_bytes

    def start(self, wav_path: Path) -> None:
        self.started = True
        self._path = wav_path
        wav_path.write_bytes(self._bytes)  # simulate ffmpeg writing audio

    def stop(self) -> Path:
        self.stopped = True
        assert self._path is not None
        return self._path


class _FakeTranscriber:
    name = "fake"

    def __init__(self, text: str = "I keep circling the same worry") -> None:
        self._text = text
        self.calls: list[Path] = []

    def transcribe(self, wav_path: Path) -> str:
        self.calls.append(wav_path)
        return self._text


# ---------------------------------------------------------------------------
# Detection + degradation
# ---------------------------------------------------------------------------


def test_voice_off_by_default_in_suite() -> None:
    assert voice.voice_enabled() is False  # conftest sets DR_ALEX_VOICE_OFF=1


def test_detect_prefers_whisper_cpp_then_mlx_then_none(monkeypatch) -> None:
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/local/bin/whisper-cli"
                        if name == "whisper-cli" else None)
    tr = voice.detect_transcriber()
    assert isinstance(tr, voice.WhisperCppTranscriber) and tr.binary.endswith("whisper-cli")

    monkeypatch.setattr(voice.shutil, "which", lambda name: None)
    monkeypatch.setattr(voice, "has_mlx_whisper", lambda: True)
    assert isinstance(voice.detect_transcriber(), voice.MlxWhisperTranscriber)

    monkeypatch.setattr(voice, "has_mlx_whisper", lambda: False)
    assert voice.detect_transcriber() is None


def test_install_hint_is_local_only_and_bans_cloud() -> None:
    hint = voice.install_hint().lower()
    assert "whisper" in hint
    assert "cloud" in hint  # explicitly says cloud STT is unsupported
    for banned in ("openai", "google", "deepgram", "assemblyai", "http"):
        assert banned not in hint


def test_available_degrades_when_no_transcriber(monkeypatch) -> None:
    monkeypatch.delenv("DR_ALEX_VOICE_OFF", raising=False)
    monkeypatch.setattr(voice, "detect_transcriber", lambda: None)
    res = voice.available()
    assert res is not None and res.degraded is True and res.hint


def test_available_off_when_voice_disabled() -> None:
    # conftest keeps DR_ALEX_VOICE_OFF=1.
    res = voice.available()
    assert res is not None and res.degraded is True


# ---------------------------------------------------------------------------
# Ephemeral audio: 0600 file under a private 0700 dir, NOT /tmp
# ---------------------------------------------------------------------------


def test_audio_tempfile_perms_and_location() -> None:
    d = voice.audio_tmp_dir()
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert not str(d).startswith("/tmp/") and not str(d).startswith("/private/tmp/")  # not shared /tmp
    f = voice.new_audio_tempfile()
    try:
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
        assert f.parent == d
        assert f.suffix == ".wav"
    finally:
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Capture → transcribe → TEXT, with audio unlinked (ephemeral)
# ---------------------------------------------------------------------------


def test_capture_and_transcribe_happy_path(monkeypatch) -> None:
    monkeypatch.delenv("DR_ALEX_VOICE_OFF", raising=False)
    tr = _FakeTranscriber("hello alex")
    monkeypatch.setattr(voice, "detect_transcriber", lambda: tr)
    rec = _FakeRecorder()

    res = voice.capture_and_transcribe(rec, transcriber=tr)
    assert res.degraded is False
    assert res.text == "hello alex"
    assert rec.started and rec.stopped
    # The audio file was created then UNLINKED (ephemeral) — nothing left behind.
    assert tr.calls, "transcriber should have been handed the wav"
    assert not tr.calls[0].exists(), "audio must be unlinked after transcription (D7)"


def test_capture_does_not_open_mic_when_degraded(monkeypatch) -> None:
    monkeypatch.delenv("DR_ALEX_VOICE_OFF", raising=False)
    monkeypatch.setattr(voice, "detect_transcriber", lambda: None)
    rec = _FakeRecorder()
    res = voice.capture_and_transcribe(rec)
    assert res.degraded is True and res.hint
    assert rec.started is False, "the mic must NOT open when there's no local transcriber"


def test_finish_capture_unlinks_even_if_transcriber_raises(monkeypatch) -> None:
    class _Boom:
        name = "boom"

        def transcribe(self, wav_path: Path) -> str:
            raise RuntimeError("transcriber exploded")

    rec = _FakeRecorder()
    wav = voice.begin_capture(rec)
    assert wav.exists()
    res = voice.finish_capture(rec, wav, transcriber=_Boom())
    assert res.text == ""  # degraded to empty text, never a crash
    assert not wav.exists(), "audio must be unlinked in finally even on transcriber error"


def test_begin_capture_writes_into_private_audio_dir() -> None:
    rec = _FakeRecorder()
    wav = voice.begin_capture(rec)
    try:
        assert wav.parent == voice.audio_tmp_dir()
        assert rec.started is True
    finally:
        wav.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Directive 1 + cloud-STT ban: voice never calls the model, never a cloud API
# ---------------------------------------------------------------------------


def test_voice_module_never_calls_the_model_or_cloud_stt() -> None:
    src = (_ROOT / "dr_alex" / "voice.py").read_text(encoding="utf-8")
    lower = src.lower()
    # No model machinery in the voice path (it only produces text; triage happens downstream).
    for model_ref in ("--append-system-prompt", "claude_bin", "from dr_alex import llm",
                      "from dr_alex import engine"):
        assert model_ref not in lower, f"voice must not touch the model path: {model_ref!r}"
    # No cloud speech-to-text IMPORTS / SDKs / network clients (the ban is structural — there is
    # no code path to a hosted API). We check imports + client calls, not the docstring prose.
    banned_imports = (
        "import openai", "from openai", "import google.cloud", "speech_v1",
        "import deepgram", "import assemblyai", "import requests", "import httpx",
        "urllib.request", "http.client",
    )
    for token in banned_imports:
        assert token not in lower, f"cloud STT / network client is banned in voice: {token!r}"
    # And no outbound URL literal anywhere in the module's CODE.
    assert "https://" not in src.split('"""', 2)[-1], "voice must not carry an outbound URL"


def test_tui_routes_voice_text_through_the_same_process_turn() -> None:
    app_src = (_ROOT / "dr_alex" / "app.py").read_text(encoding="utf-8")
    # The voice delivery path feeds transcribed text into the SAME triage-gated entrypoint.
    assert "_deliver_voice_text" in app_src
    deliver = app_src.split("def _deliver_voice_text", 1)[1].split("\n    def ", 1)[0]
    assert "self.process_turn(text)" in deliver, "voice text must go through process_turn (STEP 0)"
