"""G12 clinician-import PREP: pure transform on SYNTHETIC fixtures + the hard consent gate.

These tests NEVER read the real clinical archive and NEVER write the store.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parent.parent / "tools" / "import_clinician_sessions.py"
_spec = importlib.util.spec_from_file_location("import_clinician_sessions", _MOD_PATH)
ics = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
# Register before exec so @dataclass can resolve the module's namespace.
sys.modules[_spec.name] = ics
_spec.loader.exec_module(ics)


# Entirely synthetic distillation content (no real clinical data).
_SYNTHETIC = """\
# Session distillation (SYNTHETIC)

## Themes
- Client responds well to microscopic, same-day steps rather than grand plans.
- Fear-based motivation has run out; identity-based motivation needs building.
- ok

## Notes
- Client responds well to microscopic, same-day steps rather than grand plans.
"""


def test_transform_extracts_dedupes_and_skips_short() -> None:
    facts = ics.transform_distillation(_SYNTHETIC)
    assert any("microscopic" in f for f in facts)
    assert any("identity-based motivation" in f for f in facts)
    # "ok" is too short; the duplicate line is de-duplicated.
    assert "ok" not in facts
    assert len(facts) == 2


def test_build_candidates_provenance_and_high_sensitivity() -> None:
    cands = ics.build_candidates(
        _SYNTHETIC, source="Shreya Banerjee (psychotherapist)", session_date="2026-03-04"
    )
    assert cands, "expected candidates"
    c = cands[0]
    assert c.sensitivity == "high"
    assert c.importance <= 80
    assert "therapy" in c.tags
    assert "clinician-import" in c.tags
    assert "source-shreya" in c.tags
    # Provenance is embedded in the memory body (G6).
    body = c.render_body()
    assert "Source: Shreya Banerjee" in body
    assert "session 2026-03-04" in body


def test_pattern_docs_get_a_pattern_tag() -> None:
    # scan_archive passes extra_tags=["pattern"] for pattern docs; exercise that path.
    cands = ics.build_candidates(
        "- A recurring rumination loop after late-night scrolling.",
        source="clinical pattern doc: rumination-loop", session_date="",
        extra_tags=["pattern"],
    )
    assert cands
    assert "pattern" in cands[0].tags


def test_main_refuses_without_consent(capsys, monkeypatch) -> None:
    # If consent is absent, scan_archive must never be called (no archive read).
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("archive must not be read without consent")

    monkeypatch.setattr(ics, "scan_archive", boom)
    rc = ics.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "CONSENT REQUIRED" in err
    assert "explicitly consent" in err
    assert "REFUSED" in err


def test_main_consent_but_dry_run_reads_nothing(capsys, monkeypatch) -> None:
    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("archive must not be read in dry-run")

    monkeypatch.setattr(ics, "scan_archive", boom)
    rc = ics.main(["--i-have-praxs-explicit-consent"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "DRY-RUN" in err


def test_consent_question_names_both_clinicians() -> None:
    assert "Shreya" in ics.CONSENT_QUESTION
    assert "Pallavi" in ics.CONSENT_QUESTION
