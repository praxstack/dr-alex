"""Corpus manifest — the single source of truth for what is (and is not) indexed.

13 books are included with canonical titles (the curated *core*). The 14th, Beck's
*Cognitive Therapy of Depression*, had a broken 876-character PDF extraction and has
NO usable text: it is listed here as EXCLUDED and must WARN loudly at every index
build. It must never be silently indexed, and Dr. Alex must never pretend to cite it.

**Drop-in books (Phase 2b).** The curated ``_BOOKS`` tuple is never hand-edited to add
a book. Instead a *supplemental user manifest* — a JSON side-file that lives OUTSIDE
git-tracked code at ``<corpus_dir>/user-books.json`` — carries any book the user drops
in. ``included_books()`` / ``excluded_books()`` / ``all_books()`` return the core
``_BOOKS`` MERGED with the validated user entries. A malformed user manifest (or a
malformed entry inside it) WARNs loudly and is skipped — it never crashes ingest, and
the curated core always survives.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger("dr_alex.books")

BOOKS_DIR_ENV = "DR_ALEX_BOOKS_DIR"
DEFAULT_CORPUS_DIR = Path(
    "/Users/prax/dr-alex/data/books"
)

# The supplemental user manifest lives next to the books it registers, so a corpus is
# self-contained ("drop a file in the folder"). It is derived/private, never in git.
USER_MANIFEST_NAME = "user-books.json"

# Broken-extraction guard: a book whose usable text is under this many characters is
# treated like the Beck extraction — EXCLUDED + WARNed, never silently indexed. Beck's
# broken PDF yielded 876 chars, so 2000 is a safe floor for "there is no real book here".
MIN_USABLE_CHARS = 2000


def broken_extraction_reason(n_chars: int) -> str:
    return (
        f"broken/short extraction ({n_chars} chars < {MIN_USABLE_CHARS} min) — no usable "
        "text; must never be silently indexed or cited"
    )


@dataclass(frozen=True)
class BookSpec:
    slug: str
    title: str
    short_title: str
    authors: str
    filename: str | None
    included: bool = True
    exclusion_reason: str | None = None
    # ``origin`` distinguishes the curated core from a drop-in book; ``source`` records
    # the original dropped file (e.g. the .pdf a .txt cache was extracted from) so
    # auto-discovery never re-registers it and ``status`` can show provenance.
    origin: str = "core"
    source: str | None = None


_BOOKS: tuple[BookSpec, ...] = (
    BookSpec(
        slug="feeling-good",
        title="Feeling Good: The New Mood Therapy",
        short_title="Feeling Good",
        authors="David D. Burns",
        filename="feeling-good-the-new-mood-therapy-david-d-burns-pd.txt",
    ),
    BookSpec(
        slug="dbt-skills-workbook",
        title="The Dialectical Behavior Therapy Skills Workbook, 2nd Edition",
        short_title="DBT Skills Workbook",
        authors="Matthew McKay, Jeffrey C. Wood, Jeffrey Brantley",
        filename="the-dialectical-behavior-therapy-skills-workbook-2.txt",
    ),
    BookSpec(
        slug="mindful-way",
        title="The Mindful Way through Depression: Freeing Yourself from Chronic Unhappiness",
        short_title="The Mindful Way through Depression",
        authors="Mark Williams, John Teasdale, Zindel Segal, Jon Kabat-Zinn",
        filename="the-mindful-way-through-depression-freeing-yoursel.txt",
    ),
    BookSpec(
        slug="anxiety-phobia-workbook",
        title="The Anxiety and Phobia Workbook",
        short_title="The Anxiety and Phobia Workbook",
        authors="Edmund J. Bourne",
        filename="the-anxiety-and-phobia-workbook-edmund-j-bourne-pd.txt",
    ),
    BookSpec(
        slug="adhd-2-0",
        title="ADHD 2.0",
        short_title="ADHD 2.0",
        authors="Edward M. Hallowell, John J. Ratey",
        filename="adhd-2-0-edward-m-hallowell-m-d-john-j-ratey-etc-p.txt",
    ),
    BookSpec(
        slug="atomic-habits",
        title="Atomic Habits: Tiny Changes, Remarkable Results",
        short_title="Atomic Habits",
        authors="James Clear",
        filename="atomic-habits-tiny-changes-remarkable-results-jame.txt",
    ),
    BookSpec(
        slug="how-to-adhd",
        title="How to ADHD: An Insider's Guide to Working with Your Brain (Not Against It)",
        short_title="How to ADHD",
        authors="Jessica McCabe",
        filename="how-to-adhd-an-insiders-guide-to-working-with-your.txt",
    ),
    BookSpec(
        slug="self-compassion",
        title="Self-Compassion",
        short_title="Self-Compassion",
        authors="Kristin Neff",
        filename="self-compassion-dr-kristin-neff-pdf.txt",
    ),
    BookSpec(
        slug="taking-charge-adult-adhd",
        title="Taking Charge of Adult ADHD, 2nd Edition",
        short_title="Taking Charge of Adult ADHD",
        authors="Russell A. Barkley, Christine M. Benton",
        filename="taking-charge-of-adult-adhd-proven-strategies-to-s.txt",
    ),
    BookSpec(
        slug="procrastination-equation",
        title="The Procrastination Equation",
        short_title="The Procrastination Equation",
        authors="Piers Steel",
        filename="the-procrastination-equation-ph-d-piers-steel-pdf.txt",
    ),
    BookSpec(
        slug="driven-to-distraction",
        title="Driven to Distraction (Revised): Recognizing and Coping with Attention Deficit Disorder",
        short_title="Driven to Distraction",
        authors="Edward M. Hallowell, John J. Ratey",
        filename="driven-to-distraction-revised-recognizing-and-copi.txt",
    ),
    BookSpec(
        slug="mastering-adult-adhd",
        title="Mastering Your Adult ADHD, 2nd Edition: A Cognitive-Behavioral Treatment Program (Client Workbook)",
        short_title="Mastering Your Adult ADHD",
        authors="Steven A. Safren, Susan E. Sprich, Carol A. Perlman, Michael W. Otto",
        filename="mastering-your-adult-adhd-2nd-ed-a-cognitive-behav.txt",
    ),
    BookSpec(
        slug="tiny-habits",
        title="Tiny Habits: The Small Changes That Change Everything",
        short_title="Tiny Habits",
        authors="BJ Fogg",
        filename="tiny-habits-the-small-changes-that-change-everythi.txt",
    ),
    BookSpec(
        slug="cognitive-therapy-depression",
        title="Cognitive Therapy of Depression",
        short_title="Cognitive Therapy of Depression",
        authors="Aaron T. Beck, A. John Rush, Brian F. Shaw, Gary Emery",
        filename=None,
        included=False,
        exclusion_reason=(
            "broken PDF extraction (876 chars of 14 expected books) — no usable "
            "text; must never be silently indexed or cited"
        ),
    ),
)


def corpus_dir() -> Path:
    override = os.environ.get(BOOKS_DIR_ENV)
    return Path(override) if override else DEFAULT_CORPUS_DIR


def user_manifest_path(corpus_dir_: Path | None = None) -> Path:
    """Location of the supplemental user manifest (``<corpus_dir>/user-books.json``)."""
    return (corpus_dir_ or corpus_dir()) / USER_MANIFEST_NAME


# ---------------------------------------------------------------------------
# Supplemental user manifest (drop-in books) — validated merge, never crashes
# ---------------------------------------------------------------------------

_REQUIRED_STR_FIELDS = ("slug", "title", "filename")


def _coerce_entry(raw: object, index: int) -> BookSpec | None:
    """Validate one user-manifest entry → BookSpec, or None (WARN) if malformed."""
    if not isinstance(raw, dict):
        log.warning("USER MANIFEST: entry #%d is not an object — skipped: %r", index, raw)
        return None
    for key in _REQUIRED_STR_FIELDS:
        val = raw.get(key)
        if not isinstance(val, str) or not val.strip():
            log.warning(
                "USER MANIFEST: entry #%d missing/invalid %r — skipped: %r",
                index, key, raw,
            )
            return None
    included = raw.get("included", True)
    if not isinstance(included, bool):
        log.warning("USER MANIFEST: entry #%d 'included' not a bool — skipped: %r", index, raw)
        return None
    slug = raw["slug"].strip()
    title = raw["title"].strip()
    return BookSpec(
        slug=slug,
        title=title,
        short_title=(raw.get("short_title") or title).strip() or title,
        authors=(raw.get("authors") or "Unknown").strip() or "Unknown",
        filename=raw["filename"].strip(),
        included=included,
        exclusion_reason=(raw.get("exclusion_reason") or None),
        origin="user",
        source=(raw.get("source") or None),
    )


def user_books(corpus_dir_: Path | None = None) -> tuple[BookSpec, ...]:
    """Validated drop-in books from the user manifest.

    A malformed file (bad JSON, wrong shape) or a malformed entry WARNs loudly and is
    skipped; the curated core is never affected and ingest never crashes.
    """
    path = user_manifest_path(corpus_dir_)
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("USER MANIFEST: %s is unreadable/invalid JSON — skipped entirely: %s", path, exc)
        return ()
    if isinstance(data, dict):
        entries = data.get("books")
    elif isinstance(data, list):
        entries = data
    else:
        entries = None
    if not isinstance(entries, list):
        log.warning("USER MANIFEST: %s has no 'books' list — skipped entirely.", path)
        return ()

    out: list[BookSpec] = []
    seen: set[str] = {b.slug for b in _BOOKS}
    for i, raw in enumerate(entries):
        spec = _coerce_entry(raw, i)
        if spec is None:
            continue
        if spec.slug in seen:
            log.warning(
                "USER MANIFEST: entry #%d slug %r collides with an existing book — skipped.",
                i, spec.slug,
            )
            continue
        seen.add(spec.slug)
        out.append(spec)
    return tuple(out)


def core_books() -> tuple[BookSpec, ...]:
    """The curated, code-defined core (never mutated by drop-in books)."""
    return _BOOKS


def all_books(corpus_dir_: Path | None = None) -> tuple[BookSpec, ...]:
    return _BOOKS + user_books(corpus_dir_)


def included_books(corpus_dir_: Path | None = None) -> tuple[BookSpec, ...]:
    return tuple(b for b in all_books(corpus_dir_) if b.included)


def excluded_books(corpus_dir_: Path | None = None) -> tuple[BookSpec, ...]:
    return tuple(b for b in all_books(corpus_dir_) if not b.included)


def by_slug(slug: str, corpus_dir_: Path | None = None) -> BookSpec | None:
    for b in all_books(corpus_dir_):
        if b.slug == slug:
            return b
    return None


# ---------------------------------------------------------------------------
# Registration — append/replace a drop-in book (atomic, private perms)
# ---------------------------------------------------------------------------


def _write_user_specs(specs: list[BookSpec], corpus_dir_: Path | None = None) -> Path:
    """Atomically persist the user manifest (0600). Only user-origin specs are stored."""
    path = user_manifest_path(corpus_dir_)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "books": [
            {
                "slug": s.slug,
                "title": s.title,
                "short_title": s.short_title,
                "authors": s.authors,
                "filename": s.filename,
                "included": s.included,
                "exclusion_reason": s.exclusion_reason,
                "source": s.source,
            }
            for s in specs
        ]
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".user-books.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - best effort on odd filesystems
        pass
    return path


def register_user_book(spec: BookSpec, corpus_dir_: Path | None = None) -> BookSpec:
    """Append (or replace, keyed by slug) a drop-in book in the user manifest.

    The stored spec is always marked ``origin='user'``. Returns the stored spec.
    """
    stored = replace(spec, origin="user")
    current = [b for b in user_books(corpus_dir_) if b.slug != stored.slug]
    current.append(stored)
    _write_user_specs(current, corpus_dir_)
    return stored
