"""Press-to-talk voice input (council D7) — LOCAL transcription only, never cloud STT.

Design constraints (council D7, binding):
  * **Press-to-talk only.** Explicit start/stop, a VISIBLE recording indicator in the TUI, and
    **no always-on capture / no VAD**. The mic opens only while Prax is holding the turn.
  * **Local transcribers ONLY.** A pluggable transcriber autodetects a ``whisper-cpp`` binary or
    the ``mlx-whisper`` python package. If neither is present we degrade to text with a one-line
    install hint. **Cloud STT (OpenAI / Google / any hosted API) is BANNED** — there is no code
    path to one, by design.
  * **Audio is ephemeral.** Capture goes to a ``0600`` tempfile under a private ``~/dr-alex`` tmp
    dir (NEVER shared ``/tmp``), and the file is unlinked in a ``finally`` — never persisted,
    never logged. Audio extensions are gitignored + guarded (Directive 3).
  * **Same single entrypoint.** This module only ever produces *text*; it never calls the model.
    The transcribed text is handed back to the caller, which feeds it into the **same
    triage-gated** ``process_turn`` as typed text (Directive 1). Voice can't bypass STEP 0.

Tests inject a FAKE recorder + FAKE transcriber, so the suite never spawns ffmpeg/whisper and
never downloads a model.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_log = logging.getLogger("dr_alex.voice")

_AUDIO_TMP_ENV = "DR_ALEX_AUDIO_TMP"
_VOICE_OFF_ENV = "DR_ALEX_VOICE_OFF"

# Candidate whisper.cpp binary names across build/versions.
_WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "whisper")

_INSTALL_HINT = (
    "Voice needs a LOCAL transcriber (cloud speech-to-text is intentionally unsupported). "
    "Install one — e.g. `brew install whisper-cpp`, or `uv pip install mlx-whisper` — then "
    "restart. Until then, just type; text works exactly the same."
)


def voice_enabled() -> bool:
    """A kill-switch (mostly for tests / headless): voice is disabled when set."""
    return os.environ.get(_VOICE_OFF_ENV, "").strip().lower() not in ("1", "true", "yes", "on")


def install_hint() -> str:
    return _INSTALL_HINT


# ---------------------------------------------------------------------------
# Ephemeral audio scratch (0700 dir under ~/dr-alex, NOT /tmp; 0600 files)
# ---------------------------------------------------------------------------


def audio_tmp_dir() -> Path:
    """A private ``0700`` scratch dir for in-flight audio (NEVER shared ``/tmp`` — D7 rider 1)."""
    override = os.environ.get(_AUDIO_TMP_ENV)
    if override:
        base = Path(override)
    else:
        from dr_alex import paths

        found = paths.find("data")
        root = found.parent if found is not None else Path(__file__).resolve().parent.parent
        base = root / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    return base


def new_audio_tempfile(suffix: str = ".wav") -> Path:
    """Create an empty ``0600`` audio tempfile under :func:`audio_tmp_dir`."""
    d = audio_tmp_dir()
    fd, name = tempfile.mkstemp(prefix="voice-", suffix=suffix, dir=str(d))
    os.close(fd)
    p = Path(name)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


# ---------------------------------------------------------------------------
# Transcribers (pluggable, LOCAL only)
# ---------------------------------------------------------------------------


class Transcriber(Protocol):
    name: str

    def transcribe(self, wav_path: Path) -> str: ...


def whisper_cpp_binary() -> str | None:
    for cand in _WHISPER_CPP_BINARIES:
        found = shutil.which(cand)
        if found:
            return found
    return None


def has_mlx_whisper() -> bool:
    import importlib.util

    return importlib.util.find_spec("mlx_whisper") is not None


def _run_whisper_cpp(binary: str, wav_path: Path) -> str:
    """Spawn whisper.cpp to transcribe ``wav_path`` and return the text (LOCAL; never the model)."""
    # `-otxt` writes <wav>.txt next to the input; `-nt` = no timestamps. Read + clean up the .txt.
    out_txt = wav_path.with_suffix(wav_path.suffix + ".txt")
    try:
        subprocess.run(
            [binary, "-f", str(wav_path), "-otxt", "-nt"],
            capture_output=True, timeout=120, check=False,
        )
        text = out_txt.read_text(encoding="utf-8").strip() if out_txt.exists() else ""
        return text
    except Exception:  # noqa: BLE001 — a transcriber failure degrades to empty text, never crashes
        return ""
    finally:
        try:
            out_txt.unlink()
        except OSError:
            pass


@dataclass
class WhisperCppTranscriber:
    binary: str
    name: str = "whisper-cpp"

    def transcribe(self, wav_path: Path) -> str:
        return _run_whisper_cpp(self.binary, wav_path)


@dataclass
class MlxWhisperTranscriber:
    model: str = "mlx-community/whisper-tiny"
    name: str = "mlx-whisper"

    def transcribe(self, wav_path: Path) -> str:
        # In-process (no subprocess). Imported lazily; only constructed when the pkg is present.
        try:
            import mlx_whisper  # type: ignore

            result = mlx_whisper.transcribe(str(wav_path), path_or_hf_repo=self.model)
            return (result.get("text") or "").strip() if isinstance(result, dict) else ""
        except Exception:  # noqa: BLE001 — degrade to empty text on any transcriber error
            return ""


def detect_transcriber() -> Transcriber | None:
    """Return the first available LOCAL transcriber, or None (⇒ degrade to text)."""
    binary = whisper_cpp_binary()
    if binary:
        return WhisperCppTranscriber(binary=binary)
    if has_mlx_whisper():
        return MlxWhisperTranscriber()
    return None


def transcriber_available() -> bool:
    return detect_transcriber() is not None


# ---------------------------------------------------------------------------
# Recorder (press-to-talk; explicit start/stop, no always-on / no VAD)
# ---------------------------------------------------------------------------


class Recorder(Protocol):
    def start(self, wav_path: Path) -> None: ...

    def stop(self) -> Path: ...


def _spawn_ffmpeg_capture(wav_path: Path, *, device: str) -> subprocess.Popen:
    """Start an ffmpeg avfoundation mic capture into ``wav_path``. Returns the process handle."""
    # -f avfoundation -i ":<audio-device>" — audio only. 16kHz mono wav suits whisper.
    args = [
        "ffmpeg", "-nostdin", "-y", "-f", "avfoundation", "-i", device,
        "-ar", "16000", "-ac", "1", str(wav_path),
    ]
    return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


class FfmpegRecorder:
    """avfoundation press-to-talk recorder. Real capture; injected-out in tests.

    The mic ``device`` (default ``":default"``) may need adjusting to your audio input index —
    see ``ffmpeg -f avfoundation -list_devices true -i ""``.
    """

    def __init__(self, *, device: str = ":default") -> None:
        self.device = device
        self._proc: subprocess.Popen | None = None
        self._path: Path | None = None

    def start(self, wav_path: Path) -> None:
        self._path = wav_path
        self._proc = _spawn_ffmpeg_capture(wav_path, device=self.device)

    def stop(self) -> Path:
        assert self._path is not None, "stop() called before start()"
        if self._proc is not None:
            try:
                # 'q' tells ffmpeg to finalize the file cleanly; fall back to terminate.
                self._proc.communicate(input=b"q", timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
        return self._path


# ---------------------------------------------------------------------------
# Orchestration — capture → transcribe → return TEXT (triage happens downstream)
# ---------------------------------------------------------------------------


@dataclass
class VoiceResult:
    text: str
    degraded: bool = False  # True when no local transcriber / voice disabled → caller uses text
    reason: str | None = None
    hint: str | None = None


def transcribe_file(wav_path: Path, transcriber: Transcriber) -> str:
    try:
        return (transcriber.transcribe(wav_path) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def available() -> VoiceResult | None:
    """Return a degraded :class:`VoiceResult` if voice can't run now, else ``None`` (OK to record).

    Called on the FIRST press-to-talk press so the mic never opens when there's no local
    transcriber (or voice is disabled) — the caller shows the hint and stays on text.
    """
    if not voice_enabled():
        return VoiceResult(text="", degraded=True, reason="voice disabled", hint=install_hint())
    if detect_transcriber() is None:
        return VoiceResult(text="", degraded=True, reason="no local transcriber",
                           hint=install_hint())
    return None


def begin_capture(recorder: Recorder, *, suffix: str = ".wav") -> Path:
    """Open the mic (press-to-talk START). Returns the ephemeral ``0600`` wav path being written."""
    wav = new_audio_tempfile(suffix=suffix)
    recorder.start(wav)
    return wav


def finish_capture(
    recorder: Recorder, wav: Path, *, transcriber: Transcriber | None = None,
) -> VoiceResult:
    """Stop the mic (press-to-talk STOP), transcribe LOCALLY, and ALWAYS unlink the audio.

    Returns the transcript TEXT only — triage happens downstream when the caller feeds this into
    the same ``process_turn`` as typed text (Directive 1).
    """
    tr = transcriber or detect_transcriber()
    try:
        path = recorder.stop()
        if tr is None:
            return VoiceResult(text="", degraded=True, reason="no local transcriber",
                               hint=install_hint())
        text = transcribe_file(path, tr)
        # R3: never log the transcript body; a structured, body-free breadcrumb only.
        _log.info("voice turn transcribed (chars=%d, transcriber=%s)",
                  len(text), getattr(tr, "name", "?"))
        return VoiceResult(text=text, degraded=False)
    finally:
        # Audio is EPHEMERAL — unlink whatever we created, always (D7 rider 1).
        try:
            wav.unlink()
        except OSError:
            pass


def capture_and_transcribe(
    recorder: Recorder,
    *,
    transcriber: Transcriber | None = None,
    suffix: str = ".wav",
) -> VoiceResult:
    """One-shot capture → transcript TEXT (never the model). Splits into begin/finish internally.

    Degrades cleanly: if no local transcriber is available (or voice is disabled) we return
    ``degraded=True`` with the install hint and do NOT open the mic.
    """
    degraded = available()
    if degraded is not None:
        return degraded
    wav = begin_capture(recorder, suffix=suffix)
    return finish_capture(recorder, wav, transcriber=transcriber)
