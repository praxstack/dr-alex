"""Drop-in books — add a book without hand-editing the curated code manifest.

Two front doors, one registration path:

* ``add_book(path, ...)`` — the ``dr-alex books add <file>`` command. Copies the file into
  the corpus dir (if it isn't already there), extracts text if it's a PDF, applies the
  broken-extraction guard, and registers the book in the supplemental user manifest.
* ``discover(corpus_dir)`` — the auto-discovery step of ``dr-alex books ingest``. Picks up
  any loose ``.txt`` / ``.pdf`` in the corpus dir that isn't already registered (in the code
  manifest OR the user manifest) and registers it the same way. So "drop a file in the
  folder, run ingest" just works.

Both derive a slug + title from the filename when not given, and both mark a book
EXCLUDED (with a loud WARN) rather than silently indexing a broken extraction.

No subprocess is ever spawned here (Directive 1): PDF text comes from the in-process
``fitz`` library, and file moves use ``shutil``.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from books import extract, manifest
from books.manifest import BookSpec

log = logging.getLogger("dr_alex.books")

# Suffixes we treat as droppable primary sources for auto-discovery.
_SOURCE_SUFFIXES = frozenset({".txt", ".md", ".text", ".pdf"})


@dataclass(frozen=True)
class AddResult:
    slug: str
    title: str
    filename: str
    included: bool
    exclusion_reason: str | None
    chars: int


# ---------------------------------------------------------------------------
# slug / title derivation
# ---------------------------------------------------------------------------


def derive_slug(name: str) -> str:
    """A filesystem-and-URL-safe slug from a filename or title."""
    stem = Path(name).stem
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or "book"


def derive_title(name: str) -> str:
    """A human title from a filename stem (hyphens/underscores → spaces, title-cased)."""
    stem = Path(name).stem
    words = re.sub(r"[-_]+", " ", stem).strip()
    words = re.sub(r"\s+", " ", words)
    return words.title() if words else "Untitled Book"


def _unique_slug(base: str, corpus_dir_: Path) -> str:
    existing = {b.slug for b in manifest.all_books(corpus_dir_)}
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


# ---------------------------------------------------------------------------
# Registration core (shared by add_book + discover)
# ---------------------------------------------------------------------------


def _register_source(
    source_in_corpus: Path,
    corpus_dir_: Path,
    *,
    slug: str,
    title: str,
    authors: str,
) -> AddResult:
    """Extract (if needed), guard, and register a source file already inside the corpus."""
    source_name = source_in_corpus.name

    if extract.is_pdf(source_in_corpus):
        cache = extract.extract_to_cache(source_in_corpus, corpus_dir_)
        filename = cache.name
        text = cache.read_text(encoding="utf-8", errors="replace")
        source = source_name
    else:
        filename = source_name
        text = source_in_corpus.read_text(encoding="utf-8", errors="replace")
        source = None

    chars = len(text.strip())
    included = chars >= manifest.MIN_USABLE_CHARS
    reason = None if included else manifest.broken_extraction_reason(chars)

    spec = BookSpec(
        slug=slug,
        title=title,
        short_title=title,
        authors=authors or "Unknown",
        filename=filename,
        included=included,
        exclusion_reason=reason,
        origin="user",
        source=source,
    )
    manifest.register_user_book(spec, corpus_dir_)

    if not included:
        log.warning(
            "CORPUS EXCLUSION: %r registered but NOT indexed — %s", title, reason
        )
    return AddResult(
        slug=slug, title=title, filename=filename, included=included,
        exclusion_reason=reason, chars=chars,
    )


# ---------------------------------------------------------------------------
# add_book — `dr-alex books add <file>`
# ---------------------------------------------------------------------------


def add_book(
    path: Path | str,
    *,
    title: str | None = None,
    authors: str | None = None,
    corpus_dir_: Path | None = None,
) -> AddResult:
    """Copy ``path`` into the corpus, extract if it's a PDF, and register it.

    Raises ``FileNotFoundError`` if the file is missing, ``ValueError`` for an unsupported
    suffix, and :class:`books.extract.PdfLibraryMissing` if a PDF is dropped without the
    PDF library installed (the CLI turns that into a one-line install hint, never a crash).
    Does NOT build the index — the caller (CLI) rebuilds so it can report chunk counts.
    """
    src = Path(path).expanduser()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"no such file: {src}")
    suffix = src.suffix.lower()
    if suffix not in _SOURCE_SUFFIXES:
        raise ValueError(
            f"unsupported book type {suffix!r} — drop a .txt, .md, or .pdf file"
        )
    if extract.is_pdf(src) and not extract.pdf_support():
        raise extract.PdfLibraryMissing()

    corpus = corpus_dir_ or manifest.corpus_dir()
    corpus.mkdir(parents=True, exist_ok=True)

    # Copy into the corpus dir if it isn't already living there.
    dest = corpus / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)

    slug = _unique_slug(derive_slug(title or src.name), corpus)
    book_title = title or derive_title(src.name)
    return _register_source(
        dest, corpus, slug=slug, title=book_title, authors=authors or "Unknown"
    )


# ---------------------------------------------------------------------------
# discover — the auto-discovery step of `dr-alex books ingest`
# ---------------------------------------------------------------------------


def _known_names() -> set[str]:
    """Every filename/source already accounted for by the code or user manifest.

    Drawn from ``included_books()`` + ``excluded_books()`` — the exact sets ``build_index``
    indexes and warns over — so auto-discovery never re-registers a book those already own
    (and stays consistent with tests that monkeypatch those accessors).
    """
    names: set[str] = set()
    for b in (*manifest.included_books(), *manifest.excluded_books()):
        if b.filename:
            names.add(b.filename)
        if b.source:
            names.add(b.source)
    return names


def discover(corpus_dir_: Path | None = None) -> list[AddResult]:
    """Register any loose, unregistered ``.txt`` / ``.pdf`` in the corpus dir.

    Returns the newly-registered books (included or excluded). Missing corpus dir → ``[]``.
    A PDF found without the PDF library installed is skipped with a WARN (never a crash);
    ``.txt`` books are always picked up.
    """
    corpus = corpus_dir_ or manifest.corpus_dir()
    if not corpus.exists():
        return []

    known = _known_names()
    results: list[AddResult] = []
    for entry in sorted(corpus.iterdir()):
        if not entry.is_file():
            continue
        if entry.name == manifest.USER_MANIFEST_NAME:
            continue
        if extract.is_extraction_cache(entry):
            continue  # derived cache, never a primary source
        if entry.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        if entry.name in known:
            continue
        if extract.is_pdf(entry) and not extract.pdf_support():
            log.warning(
                "DROP-IN: %s needs PDF support to index — %s",
                entry.name, extract.PDF_INSTALL_HINT,
            )
            continue
        slug = _unique_slug(derive_slug(entry.name), corpus)
        res = _register_source(
            entry, corpus, slug=slug, title=derive_title(entry.name), authors="Unknown"
        )
        # Keep the local 'known' set current so a PDF's cache isn't re-picked this pass.
        known.add(res.filename)
        known.add(entry.name)
        results.append(res)
    return results
