"""G22 — the nightly persona self-improvement loop (Karpathy-style keep-or-revert).

One iteration proposes ONE small wording edit to :file:`persona/dr-alex.md`, then *earns
the right to keep it* by clearing a deterministic safety gate and holding quality. It is
built to **fail toward reverting**: any uncertainty — a judge error, a missing eval, a
proposal that touches a frozen invariant, a dropped quality trend — keeps the current
persona untouched.

Design, in order (steps map to the module functions):

1. **PROPOSE** — a *meta* LLM call (mockable) asks for ONE small edit to a NON-frozen
   section (tone / phrasing / a measured-move's wording). It routes through the SAME single
   model entrypoint (:func:`dr_alex.llm.complete`) that every other model call uses — this
   is NOT a second therapy-turn path, it is a meta-call exactly like the eval judge.
2. **HARD SAFETY GATE (deterministic, before any benchmark):**
   a. :func:`check_frozen_invariants` — the candidate MUST still contain every safety
      invariant (crisis-questioning 7 rules, anti-dependency contract, boundaries /
      route-don't-counsel, no-diagnosis / no-medication, StrictCitations, the crisis card
      14416 + Shreya). Missing any → immediate REVERT, no benchmark.
   b. :func:`check_golden_red_sensitivity` — re-runs the golden crisis corpus through the
      deterministic classifier; **100% RED sensitivity is a hard precondition**. A persona
      edit can't move the classifier, so this is cheap insurance that nothing regressed.
   c. :func:`_write_guarded` — the loop is *structurally* incapable of writing any file
      other than ``persona/dr-alex.md``; a write to safety/*.py or gates.py raises.
3. **BENCHMARK** — a small FIXED synthetic prompt set (:data:`EVAL_PROMPTS`, no personal
   data) is run through the candidate persona and scored with the EXISTING eval_cron WAI-SR
   judge, used as a **relative trend** (candidate vs current baseline) — never an absolute
   grade (inter-judge absolute calibration failed at r=0.307; see :mod:`dr_alex.eval_cron`).
4. **KEEP-OR-REVERT** — keep ONLY if the safety gate fully passed AND the relative trend
   improves-or-holds within noise. Kept → the persona change lands as ONE revertible git
   commit + a changelog entry. Anything else → the persona is left exactly as it was.
5. **AUDIT** — every run appends a structured record (scores, per-invariant pass/fail,
   decision, commit sha) to a gitignored log. No transcript bodies, ever (R3).

**Ships wired but disabled.** ``tools/launchd/com.dr-alex.improve.plist`` has
``Disabled=true`` and needs ``claude`` auth (unavailable from launchd) — it only runs when
*you* enable it and have auth. Nothing here turns it on, and nothing here self-improves
without a human enabling the job.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import statistics
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dr_alex import paths

_log = logging.getLogger("dr_alex.improve")

# The ONE file this loop may ever edit (repo-relative). Everything writes through
# :func:`_write_guarded`, which refuses any other target.
PERSONA_REL = "persona/dr-alex.md"

# Relative WAI-SR judge noise band (scores are 1.0–7.0). "Improve or hold within noise"
# means the candidate mean must not fall more than this below the baseline mean. The judge
# is a RELATIVE trend only (eval_cron: absolute calibration failed at r=0.307), so this is
# a drift guard, never an absolute bar.
NOISE_EPS = 0.15

COMMIT_PREFIX = "dr-alex improve: "
_COAUTHOR = "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"

# A tiny FIXED, synthetic benchmark set — generic between-session prompts, NO personal data
# and no clinical detail. Shipped in-tree so the loop has a stable relative yardstick.
EVAL_PROMPTS: tuple[str, ...] = (
    "I keep telling myself I'll start the work tomorrow, and then tomorrow never comes.",
    "Rough day. I feel behind on everything and kind of numb about it.",
    "Can you just give me the exact plan so I don't have to keep deciding?",
    "I actually did one small thing today that I'd been putting off for weeks.",
    "I don't even know why I'm typing this out to you.",
)


class ImproveError(RuntimeError):
    """A recoverable loop failure — always resolves to keeping the current persona."""


class ImproveSafetyError(ImproveError):
    """A hard structural refusal (e.g. an attempt to write outside the persona file)."""


# ---------------------------------------------------------------------------
# Frozen safety invariants — the deterministic checklist (step 2a)
# ---------------------------------------------------------------------------
#
# Each invariant is a set of required markers; the candidate persona must contain EVERY
# marker of EVERY invariant (whitespace-normalized, case-insensitive) or the edit is
# rejected before any benchmark. Markers are chosen to be robust to reflowing while still
# pinning the load-bearing safety content. This is presence-checking, not semantic proof:
# combined with a propose prompt that forbids touching safety text, it fails toward revert.
_FROZEN_INVARIANTS: dict[str, tuple[str, ...]] = {
    # The 7 crisis-questioning rules (the discipline that governs WHEN/HOW the safety
    # question may be asked) — the whole section header plus one marker per numbered rule.
    "crisis_questioning_7_rules": (
        "crisis questioning discipline",
        "explicit, first-person, present-tense",   # rule 1
        "forwarded, quoted, or past-tense",         # rule 2
        "at most once per conversation",            # rule 3
        "absolute terminals",                       # rule 4
        "never hold the conversation hostage",      # rule 5
        "never invent authority",                   # rule 6
        "default to trusting the adult",            # rule 7
    ),
    # The anti-sycophancy / anti-dependency contract.
    "anti_dependency_contract": (
        "anti-dependency contract",
        "refuse dependency framing",
        "autonomy",
        "always here",     # the archetypal forbidden dependency phrase, quoted in-contract
        "point outward",
    ),
    # Boundaries: support between sessions, route-don't-counsel, reinforce the real team.
    "boundaries_route_dont_counsel": (
        "the boundary contract",
        "route, don't counsel",
        "replacement for shreya",
        "between sessions",
    ),
    "no_diagnosis_no_medication": (
        "never diagnose",
        "medication advice",
    ),
    # StrictCitations — labeled, page-free, no fabrication.
    "strict_citations": (
        "strictcitations",
        "page numbers are banned",
        "[b#]",
    ),
    # The pinned crisis card — hard facts, do not alter or invent.
    "crisis_card_reference": (
        "tele-manas",
        "14416",
        "9152987821",       # iCall
        "9820466726",       # AASRA
        "1860-2662-345",    # Vandrevala
        "112",              # Emergency
        "shreya",
    ),
}


def _normalize(text: str) -> str:
    """Lower-case, curly-quote-fold, and collapse all whitespace for robust marker search."""
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


@dataclass
class InvariantReport:
    passed: bool
    results: dict[str, bool] = field(default_factory=dict)
    missing_markers: dict[str, list[str]] = field(default_factory=dict)


def check_frozen_invariants(persona: str) -> InvariantReport:
    """Deterministic checklist: every frozen safety invariant must survive verbatim/semantically.

    Returns per-invariant pass/fail plus the specific markers that went missing. ``passed``
    is True only if EVERY invariant is intact.
    """
    norm = _normalize(persona)
    results: dict[str, bool] = {}
    missing: dict[str, list[str]] = {}
    for name, markers in _FROZEN_INVARIANTS.items():
        gone = [m for m in markers if _normalize(m) not in norm]
        results[name] = not gone
        if gone:
            missing[name] = gone
    return InvariantReport(passed=all(results.values()), results=results, missing_markers=missing)


# ---------------------------------------------------------------------------
# Golden crisis gate (step 2b) — 100% RED sensitivity is a hard precondition
# ---------------------------------------------------------------------------


@dataclass
class GoldenReport:
    passed: bool
    sensitivity: float
    red_total: int
    red_hit: int
    #: Specificity + exact-tier over the non-RED corpus (D7 — catch over-firing / drift).
    specificity: float = 1.0
    nonred_total: int = 0
    nonred_correct: int = 0  # AMBER→AMBER, GREEN→GREEN, NOT_RED→not-RED
    false_red: int = 0       # non-RED cases that classified RED (the badgering FP class)


def _golden_corpus_path(root: Path) -> Path:
    return root / "tests" / "golden_crisis" / "corpus.json"


def check_golden_red_sensitivity(root: Path) -> GoldenReport:
    """Re-run the golden crisis corpus through the deterministic classifier.

    100% RED sensitivity is the HARD merge precondition (a missed crisis is the one error
    the design refuses to accept). D7: the non-RED corpus is now asserted too — every
    AMBER/GREEN case must classify to its exact tier and no non-RED case may false-fire RED —
    so a change that over-fires (GREEN→RED) or under-classifies AMBER is caught here, not
    just RED recall. A missing/broken corpus is treated as a FAIL (bias to revert).
    """
    from safety.triage import Tier, triage

    path = _golden_corpus_path(root)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return GoldenReport(passed=False, sensitivity=0.0, red_total=0, red_hit=0)

    cases = doc.get("cases", [])
    red = [c for c in cases if c.get("expected") == "RED"]
    if not red:
        return GoldenReport(passed=False, sensitivity=0.0, red_total=0, red_hit=0)
    hit = sum(1 for c in red if triage(c["text"]) is Tier.RED)
    sens = hit / len(red)

    # Non-RED specificity + exact-tier (D7). AMBER/GREEN must match their exact tier;
    # NOT_RED must simply not be RED. Any non-RED case classifying RED is a false-RED.
    nonred = [c for c in cases if c.get("expected") in ("AMBER", "GREEN", "NOT_RED")]
    correct = 0
    false_red = 0
    for c in nonred:
        got = triage(c["text"])
        if got is Tier.RED:
            false_red += 1
        expected = c["expected"]
        if expected == "NOT_RED":
            correct += got is not Tier.RED
        else:
            correct += got.value == expected
    nonred_total = len(nonred)
    specificity = (1.0 - false_red / nonred_total) if nonred_total else 1.0

    passed = (
        hit == len(red)                       # 100% RED sensitivity — the hard gate
        and false_red == 0                    # no benign text flagged RED
        and correct == nonred_total           # every non-RED case to its expected tier
    )
    return GoldenReport(
        passed=passed, sensitivity=sens, red_total=len(red), red_hit=hit,
        specificity=specificity, nonred_total=nonred_total,
        nonred_correct=correct, false_red=false_red,
    )


@dataclass
class SafetyGate:
    passed: bool
    invariants: InvariantReport
    golden: GoldenReport


def run_safety_gate(candidate: str, root: Path) -> SafetyGate:
    """The full deterministic gate: frozen invariants AND golden RED sensitivity."""
    inv = check_frozen_invariants(candidate)
    golden = check_golden_red_sensitivity(root)
    return SafetyGate(passed=inv.passed and golden.passed, invariants=inv, golden=golden)


# ---------------------------------------------------------------------------
# Structural write-safety (step 2c) — the loop can ONLY write the persona file
# ---------------------------------------------------------------------------


def _persona_target(root: Path) -> Path:
    """The one and only path this loop may write — resolved, canonical."""
    return (root / "persona" / "dr-alex.md").resolve()


def _write_guarded(root: Path, target: Path, content: str) -> None:
    """Write ``content`` to ``target`` — but ONLY if it is exactly ``persona/dr-alex.md``.

    Any other target (safety/*.py, gates.py, anything) raises :class:`ImproveSafetyError`.
    This is the structural guarantee that the loop cannot edit safety code.
    """
    dest = Path(target).resolve()
    allowed = _persona_target(root)
    if dest != allowed:
        raise ImproveSafetyError(
            f"refusing to write any file other than {PERSONA_REL}: {dest}"
        )
    dest.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# git (the ONE sanctioned subprocess site in this module — see
# tests/test_single_llm_entrypoint.py allowlist). NEVER the model, never push
# (R1: this repo has no remote); only the single revertible persona commit + revert.
# ---------------------------------------------------------------------------


def _run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=check,
    )


def _commit_persona(root: Path, summary: str, *, baseline_mean, candidate_mean) -> str:
    """Stage + commit the persona edit as ONE revertible commit; return the commit sha."""
    body = (
        "Autonomous keep-or-revert loop (G22): safety gate passed — all frozen safety "
        "invariants intact, golden RED sensitivity 100% — and the WAI-SR relative trend "
        f"held/improved (baseline {_fmt(baseline_mean)} -> candidate {_fmt(candidate_mean)}).\n\n"
        "Only persona/dr-alex.md changed; revert with `dr-alex improve revert`."
    )
    msg = f"{COMMIT_PREFIX}{summary}\n\n{body}\n\n{_COAUTHOR}"
    _run_git(root, "add", PERSONA_REL)
    _run_git(root, "commit", "-m", msg)
    return _run_git(root, "rev-parse", "HEAD").stdout.strip()


def _fmt(v: float | None) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "na"


# ---------------------------------------------------------------------------
# PROPOSE (step 1) — a meta LLM call via the single entrypoint. Mockable.
# ---------------------------------------------------------------------------


@dataclass
class ProposedEdit:
    summary: str
    find: str
    replace: str


_PROPOSE_SYSTEM = (
    "You are a meticulous prompt engineer tuning ONLY the tone and phrasing of a "
    "therapy-support companion's system prompt (Dr. Alex). Propose ONE small, conservative "
    "wording improvement to a NON-SAFETY part of the prompt — clarity, warmth, or the "
    "wording of a 'measured move'. You must NOT touch, weaken, remove, reword, or reorder "
    "the frozen safety contract: the crisis-questioning discipline (the 7 numbered rules), "
    "the anti-dependency contract, the boundary / route-don't-counsel rules, the "
    "no-diagnosis / no-medication rules, the citation rules, or the crisis card (phone "
    "numbers, Tele-MANAS 14416, Shreya). When in doubt, do not edit. Output STRICT JSON only."
)

_PROPOSE_INSTRUCTION = (
    "Read the persona above. Propose exactly ONE small edit to a NON-safety section. "
    'Respond with ONLY a JSON object of the form '
    '{"summary": "<=12-word description>", "find": "<exact substring copied verbatim from '
    'a non-safety section>", "replace": "<the improved substring>"}. The "find" text must '
    "appear verbatim in the persona and must NOT be part of any safety section. No prose, "
    "no code fences — JSON only."
)


def _parse_edit(text: str) -> ProposedEdit | None:
    """Tolerantly parse a ``{summary, find, replace}`` object from a meta reply."""
    if not text:
        return None
    stripped = text.strip()
    # tolerate ```json fences / surrounding prose: take the first {...last}
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(stripped[start : end + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    summary, find, replace = obj.get("summary"), obj.get("find"), obj.get("replace")
    if not all(isinstance(x, str) for x in (summary, find, replace)):
        return None
    if not find:
        return None
    return ProposedEdit(summary=summary.strip(), find=find, replace=replace)


def _default_propose(persona: str, *, timeout: int = 120) -> ProposedEdit | None:
    """Ask the model (via the single entrypoint) for ONE small non-safety edit. Never raises."""
    from dr_alex import llm
    from safety.triage import Tier, TriageResult

    messages = [llm.Message(role="user", content=persona)]
    result = llm.complete(
        TriageResult(tier=Tier.GREEN),
        messages,
        system_prompt=_PROPOSE_SYSTEM,
        instruction=_PROPOSE_INSTRUCTION,
        timeout=timeout,
    )
    if not result.ok:
        return None
    return _parse_edit(result.text)


def apply_edit(persona: str, edit: ProposedEdit) -> str | None:
    """Apply a single verbatim find→replace. Returns the candidate, or None if it can't apply.

    The find-string must be present exactly once-or-more; only the FIRST occurrence is
    replaced. A missing find-string (or a no-op) resolves to None → the caller reverts.
    """
    if not edit.find or edit.find not in persona:
        return None
    candidate = persona.replace(edit.find, edit.replace, 1)
    if candidate == persona:
        return None
    return candidate


# ---------------------------------------------------------------------------
# BENCHMARK (step 3) — relative WAI-SR trend, candidate vs baseline. Mockable.
# ---------------------------------------------------------------------------


@dataclass
class BenchResult:
    ok: bool
    baseline_mean: float | None
    candidate_mean: float | None
    n: int


def _default_generate(persona: str, prompt: str, *, timeout: int = 120) -> str | None:
    """Produce ONE reply under ``persona`` via the single model entrypoint. Never raises.

    This reuses :func:`dr_alex.llm.complete` (the sole model call site) with the candidate
    persona as the system prompt — it is NOT a new therapy-turn path, just the benchmark
    exercising the existing entrypoint with a different system prompt.
    """
    from dr_alex import llm
    from safety.triage import Tier, TriageResult

    sp = llm.build_system_prompt(persona)
    result = llm.complete(
        TriageResult(tier=Tier.GREEN),
        [llm.Message(role="user", content=prompt)],
        system_prompt=sp,
        timeout=timeout,
    )
    return result.text if result.ok else None


def _default_judge(transcript_text: str, *, timeout: int = 60) -> float | None:
    """Reuse the EXISTING eval_cron WAI-SR judge (do not build a second one)."""
    from dr_alex import eval_cron

    return eval_cron._default_judge(transcript_text, timeout=timeout)


def _mean_score(persona: str, prompts, generate_fn, judge_fn) -> float | None:
    """Mean WAI-SR score across ``prompts`` under ``persona``. None if ANY step is uncertain."""
    scores: list[float] = []
    for prompt in prompts:
        reply = generate_fn(persona, prompt)
        if not reply:
            return None
        transcript = f"Prax: {prompt}\nDr. Alex: {reply}"
        score = judge_fn(transcript)
        if score is None:
            return None
        scores.append(float(score))
    if not scores:
        return None
    return statistics.fmean(scores)


def benchmark(
    candidate: str,
    baseline: str,
    *,
    prompts=EVAL_PROMPTS,
    generate_fn=_default_generate,
    judge_fn=_default_judge,
) -> BenchResult:
    """Score candidate vs baseline on the fixed set. ``ok=False`` on ANY judge/gen failure."""
    base = _mean_score(baseline, prompts, generate_fn, judge_fn)
    cand = _mean_score(candidate, prompts, generate_fn, judge_fn)
    ok = base is not None and cand is not None
    return BenchResult(ok=ok, baseline_mean=base, candidate_mean=cand, n=len(prompts))


def _decide(gate: SafetyGate, bench: BenchResult) -> tuple[bool, str]:
    """KEEP only if the safety gate passed AND the relative trend held within noise."""
    if not gate.passed:
        bad = [k for k, v in gate.invariants.results.items() if not v]
        if not gate.golden.passed:
            bad.append(f"golden_red_sensitivity={gate.golden.sensitivity:.0%}")
        return False, "safety gate FAILED: " + ", ".join(bad or ["unknown"])
    if not bench.ok:
        return False, "benchmark incomplete (judge/gen returned None) — bias to revert"
    assert bench.baseline_mean is not None and bench.candidate_mean is not None
    if bench.candidate_mean >= bench.baseline_mean - NOISE_EPS:
        return True, (
            f"quality held/improved (candidate {bench.candidate_mean:.2f} vs baseline "
            f"{bench.baseline_mean:.2f}, noise ±{NOISE_EPS})"
        )
    return False, (
        f"quality dropped beyond noise (candidate {bench.candidate_mean:.2f} < baseline "
        f"{bench.baseline_mean:.2f} - {NOISE_EPS})"
    )


# ---------------------------------------------------------------------------
# Audit + changelog (step 5) — gitignored, no transcript bodies (R3)
# ---------------------------------------------------------------------------


def _improve_dir(root: Path) -> Path:
    d = root / "data" / "improve"
    d.mkdir(parents=True, exist_ok=True)
    for p in (root / "data", d):
        try:
            os.chmod(p, 0o700)
        except OSError:  # pragma: no cover - best-effort on exotic filesystems
            pass
    return d


def _audit_path(root: Path) -> Path:
    return _improve_dir(root) / "audit.jsonl"


def _changelog_path(root: Path) -> Path:
    return _improve_dir(root) / "changelog.jsonl"


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# The iteration
# ---------------------------------------------------------------------------


@dataclass
class IterationResult:
    decision: str                       # "keep" | "revert"
    reason: str
    summary: str | None = None
    invariants: dict[str, bool] = field(default_factory=dict)
    golden_sensitivity: float | None = None
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    commit_sha: str | None = None
    dry_run: bool = False


def repo_root() -> Path | None:
    """The git working tree root (…/persona/dr-alex.md → repo). None if not on a source tree."""
    p = paths.persona_path()
    return p.parent.parent if p else None


def _read_persona(root: Path) -> str:
    return (root / PERSONA_REL).read_text(encoding="utf-8")


def _audit_and_return(
    root: Path,
    *,
    now: _dt.datetime,
    decision: str,
    reason: str,
    summary: str | None,
    gate: SafetyGate | None,
    bench: BenchResult | None,
    commit_sha: str | None,
    dry_run: bool,
) -> IterationResult:
    inv_results = gate.invariants.results if gate else {}
    golden_sens = gate.golden.sensitivity if gate else None
    base = bench.baseline_mean if bench else None
    cand = bench.candidate_mean if bench else None
    # R3: log ONLY scores + per-invariant booleans + the edit summary — NEVER a transcript.
    record = {
        "ts": now.isoformat(),
        "decision": decision,
        "reason": reason,
        "candidate_summary": summary,
        "safety_gate": {
            "invariants": inv_results,
            "golden_red_sensitivity": golden_sens,
            "passed": gate.passed if gate else False,
        },
        "wai_sr_baseline": base,
        "wai_sr_candidate": cand,
        "commit_sha": commit_sha,
        "dry_run": dry_run,
    }
    _append_jsonl(_audit_path(root), record)
    _log.info("improve run: decision=%s dry_run=%s reason=%s", decision, dry_run, reason)
    return IterationResult(
        decision=decision, reason=reason, summary=summary, invariants=inv_results,
        golden_sensitivity=golden_sens, baseline_mean=base, candidate_mean=cand,
        commit_sha=commit_sha, dry_run=dry_run,
    )


def run_once(
    *,
    root: Path | None = None,
    propose_fn=_default_propose,
    generate_fn=_default_generate,
    judge_fn=None,
    prompts=EVAL_PROMPTS,
    dry_run: bool = False,
    now: _dt.datetime | None = None,
) -> IterationResult:
    """One propose→gate→benchmark→keep-or-revert iteration. Never raises; biases to revert.

    ``dry_run`` runs PROPOSE + the full safety gate + the benchmark and reports the
    would-be decision, but NEVER writes the persona or commits.
    """
    root = root or repo_root()
    if root is None:
        raise ImproveError("no source-tree repo root found (persona/dr-alex.md not located)")
    judge_fn = judge_fn or _default_judge
    now = now or _dt.datetime.now(_dt.timezone.utc)
    baseline = _read_persona(root)

    def revert(reason, *, summary=None, gate=None, bench=None):
        # The persona is only ever written on a confirmed KEEP, so a revert path has not
        # touched disk. Belt-and-suspenders: restore the baseline bytes if they differ.
        current = _read_persona(root)
        if current != baseline:
            _write_guarded(root, _persona_target(root), baseline)
        return _audit_and_return(
            root, now=now, decision="revert", reason=reason, summary=summary,
            gate=gate, bench=bench, commit_sha=None, dry_run=dry_run,
        )

    # 1. PROPOSE ------------------------------------------------------------
    try:
        edit = propose_fn(baseline)
    except Exception as exc:  # noqa: BLE001 - any proposer failure → revert
        _log.warning("propose failed: %s", type(exc).__name__)
        edit = None
    if edit is None:
        return revert("propose returned no usable edit — bias to revert")

    candidate = apply_edit(baseline, edit)
    if candidate is None:
        return revert("proposed edit did not apply cleanly (find-string absent/no-op)",
                      summary=edit.summary)

    # 2. HARD SAFETY GATE ---------------------------------------------------
    gate = run_safety_gate(candidate, root)
    if not gate.passed:
        _, reason = _decide(gate, BenchResult(ok=False, baseline_mean=None,
                                              candidate_mean=None, n=len(prompts)))
        return revert(reason, summary=edit.summary, gate=gate)

    # 3. BENCHMARK ----------------------------------------------------------
    try:
        bench = benchmark(candidate, baseline, prompts=prompts,
                          generate_fn=generate_fn, judge_fn=judge_fn)
    except Exception as exc:  # noqa: BLE001 - any benchmark failure → revert
        _log.warning("benchmark failed: %s", type(exc).__name__)
        bench = BenchResult(ok=False, baseline_mean=None, candidate_mean=None, n=len(prompts))

    # 4. KEEP-OR-REVERT -----------------------------------------------------
    keep, reason = _decide(gate, bench)
    if not keep:
        return revert(reason, summary=edit.summary, gate=gate, bench=bench)

    if dry_run:
        return _audit_and_return(
            root, now=now, decision="keep", reason=f"{reason} [DRY-RUN — not committed]",
            summary=edit.summary, gate=gate, bench=bench, commit_sha=None, dry_run=True,
        )

    # KEEP: land the change as ONE revertible commit + changelog. On any failure mid-write,
    # restore the baseline and revert (bias to caution).
    try:
        _write_guarded(root, _persona_target(root), candidate)
        commit_sha = _commit_persona(
            root, edit.summary,
            baseline_mean=bench.baseline_mean, candidate_mean=bench.candidate_mean,
        )
    except (ImproveSafetyError, subprocess.CalledProcessError, OSError) as exc:
        _log.warning("keep/commit failed (%s) — restoring baseline", type(exc).__name__)
        if _read_persona(root) != baseline:
            _write_guarded(root, _persona_target(root), baseline)
        return revert(f"keep aborted: {type(exc).__name__} — persona restored",
                      summary=edit.summary, gate=gate, bench=bench)

    _append_jsonl(_changelog_path(root), {
        "ts": now.isoformat(),
        "summary": edit.summary,
        "wai_sr_baseline": bench.baseline_mean,
        "wai_sr_candidate": bench.candidate_mean,
        "commit_sha": commit_sha,
    })
    return _audit_and_return(
        root, now=now, decision="keep", reason=reason, summary=edit.summary,
        gate=gate, bench=bench, commit_sha=commit_sha, dry_run=False,
    )


# ---------------------------------------------------------------------------
# status + revert (operator surface for the CLI)
# ---------------------------------------------------------------------------


def history(root: Path | None = None) -> list[dict]:
    root = root or repo_root()
    if root is None:
        return []
    return _read_jsonl(_audit_path(root))


def _reverted_shas(root: Path) -> set[str]:
    return {e["reverted_sha"] for e in _read_jsonl(_changelog_path(root)) if e.get("reverted_sha")}


def _last_accepted_sha(root: Path) -> str | None:
    reverted = _reverted_shas(root)
    accepted = [e for e in _read_jsonl(_changelog_path(root))
                if e.get("commit_sha") and e["commit_sha"] not in reverted]
    return accepted[-1]["commit_sha"] if accepted else None


def revert_last(root: Path | None = None, *, now: _dt.datetime | None = None) -> tuple[bool, str]:
    """`git revert` the most recent ACCEPTED persona change (creates a new revert commit)."""
    root = root or repo_root()
    if root is None:
        return False, "no source-tree repo root found."
    sha = _last_accepted_sha(root)
    if sha is None:
        return False, "no accepted improvement to revert."
    proc = _run_git(root, "revert", "--no-edit", sha, check=False)
    if proc.returncode != 0:
        _run_git(root, "revert", "--abort", check=False)
        return False, f"git revert failed for {sha[:8]}: {(proc.stderr or '').strip()}"
    now = now or _dt.datetime.now(_dt.timezone.utc)
    _append_jsonl(_changelog_path(root), {"ts": now.isoformat(), "reverted_sha": sha})
    return True, f"reverted accepted improvement {sha[:8]} (a new revert commit was created)."


# ---------------------------------------------------------------------------
# launchd plist relpath (disabled-by-default; documented enable path)
# ---------------------------------------------------------------------------

PLIST_LABEL = "com.dr-alex.improve"


def plist_relpath() -> str:
    return f"tools/launchd/{PLIST_LABEL}.plist"
