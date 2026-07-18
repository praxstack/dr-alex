"""G22 — the persona self-improvement keep-or-revert loop.

Every test uses a MOCKED proposer, generator, and judge (never a real model) and operates
on a throwaway git repo seeded with a COPY of the real persona + golden corpus — the real
``persona/dr-alex.md`` is never mutated. The suite proves the loop:

  * keeps an improvement (persona changed, ONE commit, changelog appended);
  * reverts when a frozen safety invariant goes missing (persona untouched, no commit);
  * reverts when golden RED sensitivity drops below 100%;
  * reverts when the WAI-SR relative trend drops;
  * reverts (bias to caution) when the judge returns None;
  * is STRUCTURALLY unable to write any file other than persona/dr-alex.md;
  * can `improve revert` the last accepted change;
  * never writes transcript bodies to the audit log (R3).
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dr_alex import improve

_REAL_ROOT = Path(__file__).resolve().parent.parent
_UTC = _dt.timezone.utc
_NOW = _dt.datetime(2026, 7, 18, 3, 45, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def _tmp_repo(tmp_path: Path) -> Path:
    """A throwaway git repo seeded with a COPY of the real persona + golden corpus."""
    root = tmp_path / "repo"
    (root / "persona").mkdir(parents=True)
    (root / "tests" / "golden_crisis").mkdir(parents=True)
    shutil.copy(_REAL_ROOT / "persona" / "dr-alex.md", root / "persona" / "dr-alex.md")
    shutil.copy(
        _REAL_ROOT / "tests" / "golden_crisis" / "corpus.json",
        root / "tests" / "golden_crisis" / "corpus.json",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _persona(root: Path) -> str:
    return (root / improve.PERSONA_REL).read_text(encoding="utf-8")


# A safe (non-frozen) edit: adds a word to the opening description.
_SAFE_FIND = "warm, steady coaching companion"
_SAFE_REPLACE = "warm, steady, grounded coaching companion"


def _propose_safe(_persona_text: str) -> improve.ProposedEdit:
    return improve.ProposedEdit(summary="warmer opening descriptor",
                                find=_SAFE_FIND, replace=_SAFE_REPLACE)


def _gen_persona_aware(persona: str, prompt: str) -> str:
    """Reply text differs by persona so a mocked judge can score candidate vs baseline."""
    tag = "CANDIDATE_REPLY" if _SAFE_REPLACE in persona else "BASELINE_REPLY"
    return f"{tag} to: {prompt}"


def _judge_candidate_better(transcript: str):
    return 6.0 if "CANDIDATE_REPLY" in transcript else 5.0


def _judge_candidate_worse(transcript: str):
    return 4.0 if "CANDIDATE_REPLY" in transcript else 6.0


_PROMPTS = ("prompt one", "prompt two")


# ---------------------------------------------------------------------------
# invariant + golden sanity (against the real, unmodified persona)
# ---------------------------------------------------------------------------


def test_real_persona_satisfies_all_frozen_invariants() -> None:
    rep = improve.check_frozen_invariants(_persona(_REAL_ROOT))
    assert rep.passed, f"real persona is missing invariants: {rep.missing_markers}"
    assert set(rep.results) == set(improve._FROZEN_INVARIANTS)
    assert all(rep.results.values())


def test_golden_gate_is_100pct_on_real_corpus() -> None:
    g = improve.check_golden_red_sensitivity(_REAL_ROOT)
    assert g.passed and g.sensitivity == 1.0 and g.red_total > 0


# ---------------------------------------------------------------------------
# KEEP
# ---------------------------------------------------------------------------


def test_keep_accepts_improvement_and_commits(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    res = improve.run_once(
        root=root, propose_fn=_propose_safe, generate_fn=_gen_persona_aware,
        judge_fn=_judge_candidate_better, prompts=_PROMPTS, now=_NOW,
    )

    assert res.decision == "keep", res.reason
    # persona changed on disk
    after = _persona(root)
    assert after != before and _SAFE_REPLACE in after
    # exactly ONE new commit, prefixed + co-authored + revertible
    assert res.commit_sha
    msg = _git(root, "log", "-1", "--format=%B")
    assert msg.startswith(improve.COMMIT_PREFIX)
    assert "Co-Authored-By: Claude Opus 4.8" in msg
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "2"  # seed + this one
    # only persona/dr-alex.md changed in that commit
    changed = _git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == [improve.PERSONA_REL]
    # changelog appended with the commit sha; audit appended
    changelog = improve._read_jsonl(improve._changelog_path(root))
    assert changelog and changelog[-1]["commit_sha"] == res.commit_sha
    audit = improve.history(root)
    assert audit and audit[-1]["decision"] == "keep"
    assert audit[-1]["safety_gate"]["passed"] is True


def test_dry_run_gates_and_benchmarks_but_never_commits(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    res = improve.run_once(
        root=root, propose_fn=_propose_safe, generate_fn=_gen_persona_aware,
        judge_fn=_judge_candidate_better, prompts=_PROMPTS, now=_NOW, dry_run=True,
    )

    assert res.decision == "keep" and res.dry_run and res.commit_sha is None
    assert _persona(root) == before                      # untouched
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "1"  # no new commit
    assert res.candidate_mean == 6.0 and res.baseline_mean == 5.0


# ---------------------------------------------------------------------------
# REVERT paths
# ---------------------------------------------------------------------------


def test_revert_when_frozen_invariant_missing(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    # This edit deletes the "route, don't counsel" boundary marker → invariant fails.
    def propose_bad(_p):
        return improve.ProposedEdit(summary="reword boundary",
                                    find="route, don't counsel",
                                    replace="help however feels right")

    calls = {"gen": 0, "judge": 0}

    def gen(p, prompt):
        calls["gen"] += 1
        return "x"

    def judge(t):
        calls["judge"] += 1
        return 5.0

    res = improve.run_once(root=root, propose_fn=propose_bad, generate_fn=gen,
                           judge_fn=judge, prompts=_PROMPTS, now=_NOW)

    assert res.decision == "revert"
    assert "safety gate" in res.reason.lower()
    assert res.invariants["boundaries_route_dont_counsel"] is False
    # gate short-circuits BEFORE any benchmark, and persona is untouched, no commit
    assert calls == {"gen": 0, "judge": 0}
    assert _persona(root) == before
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "1"


def test_revert_when_golden_red_sensitivity_below_100(tmp_path, monkeypatch) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    # Simulate a classifier regression: triage now misses RED. The persona edit itself is
    # benign (invariants intact), so ONLY the golden gate can fail here. (Patch the module
    # object — the `safety` package re-exports `triage`, which shadows the submodule name.)
    import importlib
    triage_mod = importlib.import_module("safety.triage")
    monkeypatch.setattr(triage_mod, "triage", lambda text, *a, **k: triage_mod.Tier.GREEN)

    res = improve.run_once(root=root, propose_fn=_propose_safe,
                           generate_fn=_gen_persona_aware, judge_fn=_judge_candidate_better,
                           prompts=_PROMPTS, now=_NOW)

    assert res.decision == "revert"
    assert res.golden_sensitivity == 0.0
    assert "golden" in res.reason.lower() or "sensitivity" in res.reason.lower()
    # frozen invariants were fine; it was the golden gate that fenced it
    assert all(res.invariants.values())
    assert _persona(root) == before
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "1"


def test_revert_when_wai_sr_trend_drops(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    res = improve.run_once(root=root, propose_fn=_propose_safe,
                           generate_fn=_gen_persona_aware, judge_fn=_judge_candidate_worse,
                           prompts=_PROMPTS, now=_NOW)

    assert res.decision == "revert"
    assert "quality dropped" in res.reason
    assert res.candidate_mean == 4.0 and res.baseline_mean == 6.0
    assert _persona(root) == before
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "1"


def test_revert_when_judge_returns_none(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    res = improve.run_once(root=root, propose_fn=_propose_safe,
                           generate_fn=_gen_persona_aware, judge_fn=lambda t: None,
                           prompts=_PROMPTS, now=_NOW)

    assert res.decision == "revert"
    assert "incomplete" in res.reason or "bias to revert" in res.reason
    assert _persona(root) == before
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "1"


def test_revert_when_propose_returns_none(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)
    res = improve.run_once(root=root, propose_fn=lambda p: None, prompts=_PROMPTS, now=_NOW)
    assert res.decision == "revert" and "propose" in res.reason
    assert _persona(root) == before


def test_revert_when_edit_does_not_apply(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    def propose_absent(_p):
        return improve.ProposedEdit(summary="x", find="THIS STRING IS NOT IN THE PERSONA",
                                    replace="y")

    res = improve.run_once(root=root, propose_fn=propose_absent, prompts=_PROMPTS, now=_NOW)
    assert res.decision == "revert" and "did not apply" in res.reason
    assert _persona(root) == before


# ---------------------------------------------------------------------------
# STRUCTURAL: cannot write any file other than persona/dr-alex.md
# ---------------------------------------------------------------------------


def test_write_guard_blocks_safety_and_gates_files(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    # seed a couple of decoy files to prove they are never touched
    (root / "safety").mkdir()
    triage = root / "safety" / "triage.py"
    gates = root / "dr_alex" / "gates.py"
    gates.parent.mkdir(parents=True)
    triage.write_text("ORIGINAL_TRIAGE")
    gates.write_text("ORIGINAL_GATES")

    for bad in (triage, gates, root / "persona" / "evil.md",
                root / "persona" / ".." / "safety" / "crisis_card.py"):
        with pytest.raises(improve.ImproveSafetyError):
            improve._write_guarded(root, bad, "HACKED")

    assert triage.read_text() == "ORIGINAL_TRIAGE"
    assert gates.read_text() == "ORIGINAL_GATES"
    # positive control: the persona target IS writable
    improve._write_guarded(root, root / "persona" / "dr-alex.md", "NEW PERSONA BODY")
    assert _persona(root) == "NEW PERSONA BODY"


# ---------------------------------------------------------------------------
# improve revert
# ---------------------------------------------------------------------------


def test_improve_revert_restores_prior_persona(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    before = _persona(root)

    kept = improve.run_once(root=root, propose_fn=_propose_safe,
                            generate_fn=_gen_persona_aware, judge_fn=_judge_candidate_better,
                            prompts=_PROMPTS, now=_NOW)
    assert kept.decision == "keep"
    assert _persona(root) != before

    ok, msg = improve.revert_last(root, now=_NOW)
    assert ok, msg
    # the persona is byte-for-byte the prior version again…
    assert _persona(root) == before
    # …via a NEW revert commit (history moves forward, nothing rewritten)
    assert _git(root, "rev-list", "--count", "HEAD").strip() == "3"  # seed + keep + revert

    # a second revert has nothing left to undo
    ok2, msg2 = improve.revert_last(root, now=_NOW)
    assert not ok2 and "no accepted improvement" in msg2


# ---------------------------------------------------------------------------
# R3: the audit log carries scores + decisions, never transcript bodies
# ---------------------------------------------------------------------------


def test_audit_log_has_no_transcript_bodies(tmp_path) -> None:
    root = _tmp_repo(tmp_path)
    secret = "SECRET_TRANSCRIPT_BODY_THAT_MUST_NEVER_BE_LOGGED"

    def gen(persona, prompt):
        tag = "CANDIDATE_REPLY" if _SAFE_REPLACE in persona else "BASELINE_REPLY"
        return f"{tag} {secret}"

    res = improve.run_once(root=root, propose_fn=_propose_safe, generate_fn=gen,
                           judge_fn=_judge_candidate_better, prompts=_PROMPTS, now=_NOW)
    assert res.decision == "keep"
    audit_text = improve._audit_path(root).read_text(encoding="utf-8")
    changelog_text = improve._changelog_path(root).read_text(encoding="utf-8")
    assert secret not in audit_text
    assert secret not in changelog_text
    # but the scores + decision ARE recorded
    rec = json.loads(audit_text.splitlines()[-1])
    assert rec["decision"] == "keep"
    assert rec["wai_sr_candidate"] == 6.0 and rec["wai_sr_baseline"] == 5.0
    assert rec["safety_gate"]["invariants"]["crisis_questioning_7_rules"] is True
