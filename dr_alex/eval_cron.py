"""G13 — nightly eval cron, DISABLED BY DEFAULT (gardener enable pattern).

A WAI-SR-style (Working Alliance Inventory, Short Revised) LLM judge scores recent sessions
so drift is *detectable*. Two hard lessons are baked in:

  1. **Relative trend only — never an absolute grade.** Inter-judge agreement on absolute
     WAI-SR scores failed at r=0.307 (calibration is unreliable), while the *monotonic
     ordering* held. So we use scores only for a rolling **z-score drift alarm** — "this
     session scored well below the recent run of sessions" — never as a standalone quality
     number. :data:`ABSOLUTE_CALIBRATION_R` documents the failure inline.
  2. **No silent decay (G8/anti-pattern #3).** A background loop that stops running must be
     loud. :func:`liveness` distinguishes an honest *quiet week* (no new sessions to score —
     expected) from a *watchdog-blind* loop (the cron itself hasn't completed in N days).

Privacy (R3): transcripts are decrypted **in memory** from ``state.db`` and handed to the
single model entrypoint; only the resulting numeric score + z are persisted/logged — never a
byte of transcript content.

**This ships wired but disabled.** The launchd plist (``tools/launchd/com.dr-alex.eval.plist``)
has ``Disabled=true``; one command (documented there) enables it. Nothing here turns it on.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import statistics
from dataclasses import dataclass, field

from dr_alex import statedb

_log = logging.getLogger("dr_alex.eval")

#: Documented inter-judge agreement on ABSOLUTE WAI-SR scores (calibration failure).
ABSOLUTE_CALIBRATION_R = 0.307

#: z-score magnitude beyond which a session is flagged as drift (relative, not absolute).
DRIFT_Z_THRESHOLD = 2.0

#: If the eval loop hasn't completed in this many days, it's "watchdog blind" (loud).
LIVENESS_STALE_DAYS = 3

_JUDGE_SYSTEM = (
    "You are a silent evaluation judge scoring the therapeutic working alliance in ONE "
    "session transcript between a support companion (Dr. Alex) and Prax, on the WAI-SR "
    "dimensions (bond, goal, task). Output a SINGLE number from 1.0 (poor alliance) to 7.0 "
    "(excellent). Judge relative quality only. Output ONLY the number."
)


@dataclass
class SessionScore:
    session_id: str
    score: float
    z: float | None = None
    drift_flagged: bool = False


@dataclass
class EvalRunResult:
    scored: list[SessionScore] = field(default_factory=list)
    drift_alarms: list[str] = field(default_factory=list)
    liveness_banner: str | None = None
    ran: bool = True


def _default_judge(transcript_text: str, *, timeout: int = 60) -> float | None:
    """Route the judge through the ONE model entrypoint (Directive 1). Returns a score or None.

    The transcript stays in memory here; it is passed to the model via stdin, never written
    to disk or logged.
    """
    from dr_alex import llm
    from safety.triage import Tier, TriageResult

    messages = [llm.Message(role="user", content=transcript_text)]
    result = llm.complete(
        TriageResult(tier=Tier.GREEN),
        messages,
        system_prompt=_JUDGE_SYSTEM,
        instruction="Score this transcript's working alliance 1.0–7.0. Output ONLY the number.",
        timeout=timeout,
    )
    if not result.ok:
        return None
    return _parse_score(result.text)


def _parse_score(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    return max(1.0, min(v, 7.0))


def _transcript_text(turns) -> str:
    """Render a decrypted transcript for the judge (in-memory only)."""
    lines = []
    for t in turns:
        who = "Prax" if t.role == "user" else "Dr. Alex"
        lines.append(f"{who}: {t.body}")
    return "\n".join(lines)


def _already_scored(path=None) -> set[str]:
    if not statedb.telemetry_enabled():
        return set()
    try:
        with statedb._connect(path) as conn:
            return {r[0] for r in conn.execute(
                "SELECT DISTINCT session_id FROM eval_scores WHERE session_id IS NOT NULL"
            ).fetchall()}
    except Exception:  # noqa: BLE001
        return set()


def liveness(*, now: _dt.datetime | None = None, path=None) -> str | None:
    """A loud banner when the eval loop looks blind — distinct from an honest quiet week."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    last = statedb.last_eval_at(path=path)
    pending = [s for s in statedb.session_ids_with_transcripts(path=path) if s not in _already_scored(path)]
    if last is None:
        # Never run. Only loud if there's actually input waiting (else it's a quiet week).
        if pending:
            return "eval watchdog has NEVER run but sessions are waiting — the loop may be blind."
        return None
    last_dt = _dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
    age_days = (now.astimezone(_dt.timezone.utc) - last_dt).days
    if age_days > LIVENESS_STALE_DAYS and pending:
        return (
            f"eval watchdog last ran {age_days}d ago with sessions waiting — the loop may be "
            "blind (not just a quiet week)."
        )
    return None


def run_eval(
    *,
    now: _dt.datetime | None = None,
    judge_fn=_default_judge,
    path=None,
    max_sessions: int = 5,
) -> EvalRunResult:
    """Score up-to ``max_sessions`` unscored (non-test) sessions; flag relative drift. Never raises.

    Only scores are persisted (``eval_scores``) and logged; transcript content never leaves
    memory (R3). Returns the run summary including any z-score drift alarms + a liveness banner.
    """
    if not statedb.telemetry_enabled():
        return EvalRunResult(ran=False)

    now = now or _dt.datetime.now(_dt.timezone.utc)
    scored_ids = _already_scored(path)
    pending = [s for s in statedb.session_ids_with_transcripts(path=path) if s not in scored_ids]
    result = EvalRunResult()

    for sid in pending[:max_sessions]:
        turns = statedb.load_transcript(sid, path=path)  # decrypt in memory
        if not turns:
            continue
        try:
            score = judge_fn(_transcript_text(turns))
        except Exception as exc:  # noqa: BLE001 — a judge failure must not crash the cron
            _log.warning("eval judge failed for a session: %s", type(exc).__name__)
            continue
        if score is None:
            continue

        history = statedb.recent_eval_scores(limit=30, path=path)
        z = _zscore(score, history)
        drift = z is not None and abs(z) >= DRIFT_Z_THRESHOLD
        statedb.record_eval_score(score, session_id=sid, z=z, judge_model="wai-sr-judge",
                                  now=now, path=path)
        # R3: log ONLY the score + z, never the transcript.
        _log.info("eval session scored: score=%.2f z=%s drift=%s", score,
                  f"{z:.2f}" if z is not None else "na", drift)
        ss = SessionScore(session_id=sid, score=score, z=z, drift_flagged=drift)
        result.scored.append(ss)
        if drift:
            result.drift_alarms.append(
                f"session scored {score:.1f} (z={z:.1f}) — a relative drop vs recent sessions."
            )

    result.liveness_banner = liveness(now=now, path=path)
    return result


def _zscore(value: float, history: list[float]) -> float | None:
    """z of ``value`` against ``history`` (needs ≥2 priors with spread). Relative-only signal."""
    if len(history) < 2:
        return None
    mean = statistics.fmean(history)
    try:
        sd = statistics.stdev(history)
    except statistics.StatisticsError:
        return None
    if sd == 0:
        return None
    return (value - mean) / sd
