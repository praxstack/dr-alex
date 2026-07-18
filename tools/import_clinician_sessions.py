#!/usr/bin/env python3
"""G12 — clinician-session import (CONSENT-GATED PREP; DO NOT RUN without Prax's yes).

This script *would* ingest the distilled clinician-archive material — Shreya's four
psychotherapy sessions, Dr. Pallavi's two psychiatry sessions, and the named living
pattern docs — into the canonical memory store as ``sensitivity:high`` therapy memories
with clinician provenance tags. It is deliberately inert until Prax explicitly consents:

  * It **refuses to do anything** without the ``--i-have-praxs-explicit-consent`` flag, and
    it prints the consent question every time it is invoked.
  * Even *with* consent it defaults to a dry-run preview; actual writes require ``--execute``.
  * The real archive at ``.hermes/.../clinical-archive`` is on a READ-ONLY backup volume and
    is only ever read (never written) — and only under ``--execute``.

Trust ordering (G6): these are the most trustworthy personal memories (real clinicians),
above the book library, Prax's own notes, and any prior AI self. Each imported fact records
its clinician source + session date. Writes go through ``memctl`` (store invariant 3) as
``dr-alex``, importance clamped ≤80 like every other Dr. Alex write.

Tests exercise the pure transform (:func:`transform_distillation`, :func:`build_candidates`)
with SYNTHETIC fixtures ONLY — they never read the real archive and never write the store.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The real (read-only) source. Never read except under --execute.
DEFAULT_ARCHIVE = Path(
    "/Volumes/PraxSSD/MacBookAir-Reset-Backup/.hermes/projects/therapy-stack/clinical-archive"
)

#: Which distillation file inside a session dir we import (a DISTILLATION, never the raw
#: transcript — we import clinical insight, not verbatim session audio/text).
SESSION_DISTILLATION = "transcript.insights.md"

#: Clinician provenance by archive subdir.
CLINICIAN_SOURCES = {
    "shreya-banerjee": "Shreya Banerjee (psychotherapist)",
    "dr-pallavi": "Dr. Pallavi Joshi (psychiatrist)",
}

IMPORT_IMPORTANCE = 75  # high-trust, but still within the ≤80 dr-alex clamp

CONSENT_QUESTION = (
    "CONSENT REQUIRED — this imports Prax's real clinician-session distillations (Shreya x4, "
    "Dr. Pallavi x2, and the pattern docs) into the durable memory store as sensitivity:high "
    "therapy memories.\n"
    "Question for Prax: \"Do you explicitly consent to importing your Shreya and Dr. Pallavi "
    "session distillations and pattern docs into Dr. Alex's long-term memory as private, "
    "high-sensitivity notes?\"\n"
    "If yes, re-run with:  --i-have-praxs-explicit-consent --execute"
)


# ---------------------------------------------------------------------------
# Pure transform (unit-tested on synthetic fixtures).
# ---------------------------------------------------------------------------


@dataclass
class MemoryCandidate:
    body: str
    tags: list[str]
    sensitivity: str = "high"
    importance: int = IMPORT_IMPORTANCE
    memtype: str = "user"
    source: str = ""
    session_date: str = ""

    def render_body(self) -> str:
        """The memory body carries an explicit provenance line (G6)."""
        prov = f"Source: {self.source}"
        if self.session_date:
            prov += f" — session {self.session_date}"
        return f"{self.body.strip()}\n\n{prov}"


_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s+")


def transform_distillation(text: str) -> list[str]:
    """Extract durable clinical fact lines from a distillation markdown (synthetic-safe).

    Conservative + deterministic: bullet lines become candidate facts; headings/blank lines
    are dropped. This is a PREP transform — the real ingestion (once consented) may refine
    it, but it never invents content, only selects and trims what the clinician wrote.
    """
    facts: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        if _HEADING.match(raw):
            continue
        m = _BULLET.match(raw)
        if not m:
            continue
        fact = re.sub(r"\s+", " ", m.group(1)).strip()
        fact = re.sub(r"^\[[ xX]\]\s*", "", fact).strip()  # drop markdown checkbox markers ([ ] / [x])
        if len(fact) < 8:  # skip trivially short fragments
            continue
        key = fact.lower()
        if key in seen:
            continue
        seen.add(key)
        facts.append(fact[:400])
    return facts


def build_candidates(text: str, *, source: str, session_date: str,
                     extra_tags: list[str] | None = None) -> list[MemoryCandidate]:
    """Turn one distillation into one MemoryCandidate per durable fact (one fact per memory)."""
    source_slug = _source_slug(source)
    tags = ["therapy", "clinician-import", source_slug]
    if extra_tags:
        tags += [t for t in extra_tags if t not in tags]
    return [
        MemoryCandidate(body=fact, tags=list(tags), source=source, session_date=session_date)
        for fact in transform_distillation(text)
    ]


def _source_slug(source: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    return f"source-{base.split('-')[0] or 'clinician'}"


# ---------------------------------------------------------------------------
# Archive discovery (only touched under --execute).
# ---------------------------------------------------------------------------


@dataclass
class ImportPlan:
    candidates: list[MemoryCandidate] = field(default_factory=list)
    sessions_seen: int = 0
    patterns_seen: int = 0


def scan_archive(archive: Path) -> ImportPlan:
    """Read the READ-ONLY archive and build the import plan. Never writes anything."""
    plan = ImportPlan()
    sessions_root = archive / "01-sessions"
    for clinician_dir, source in CLINICIAN_SOURCES.items():
        base = sessions_root / clinician_dir
        if not base.is_dir():
            continue
        for session_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            distill = session_dir / SESSION_DISTILLATION
            if not distill.is_file():
                continue
            plan.sessions_seen += 1
            text = distill.read_text(encoding="utf-8", errors="replace")
            plan.candidates += build_candidates(
                text, source=source, session_date=session_dir.name
            )
    patterns_root = archive / "04-patterns"
    if patterns_root.is_dir():
        for doc in sorted(patterns_root.glob("*.md")):
            if doc.name.upper() == "README.MD":
                continue
            plan.patterns_seen += 1
            text = doc.read_text(encoding="utf-8", errors="replace")
            plan.candidates += build_candidates(
                text, source=f"clinical pattern doc: {doc.stem}", session_date="",
                extra_tags=["pattern"],
            )
    return plan


# ---------------------------------------------------------------------------
# CLI (hard consent gate).
# ---------------------------------------------------------------------------


def _write_candidate(cand: MemoryCandidate) -> bool:
    """Write one candidate via the memctl bridge (only reached under --execute)."""
    # Imported lazily so the module (and its tests) never require the dr_alex package env.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from dr_alex import memstore

    res = memstore.remember(
        cand.render_body(), tags=cand.tags, sensitivity=cand.sensitivity,
        importance=cand.importance, memtype=cand.memtype,
    )
    return res.ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="import_clinician_sessions",
        description="G12 consent-gated clinician-session import (PREP; refuses without consent).",
    )
    parser.add_argument("--i-have-praxs-explicit-consent", dest="consent", action="store_true")
    parser.add_argument("--execute", action="store_true",
                        help="actually read the archive + write memories (else dry-run preview)")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args(argv)

    # The consent question is printed on EVERY invocation.
    print(CONSENT_QUESTION, file=sys.stderr)

    if not args.consent:
        print("\nREFUSED: consent flag absent. Nothing was read or written.", file=sys.stderr)
        return 2

    if not args.execute:
        print("\nConsent flag present, but running in DRY-RUN (no --execute): "
              "no archive read, no writes. Re-run with --execute to proceed.", file=sys.stderr)
        return 0

    if not args.archive.is_dir():
        print(f"\nArchive not found: {args.archive}", file=sys.stderr)
        return 1

    plan = scan_archive(args.archive)
    print(f"\nPlanned import: {len(plan.candidates)} facts from {plan.sessions_seen} sessions "
          f"+ {plan.patterns_seen} pattern docs.", file=sys.stderr)
    written = 0
    for cand in plan.candidates:
        if _write_candidate(cand):
            written += 1
    print(f"Wrote {written}/{len(plan.candidates)} memories via memctl (dr-alex, high-sens).",
          file=sys.stderr)
    return 0 if written == len(plan.candidates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
