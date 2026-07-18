"""Lightweight, offline text extraction for drop-in books (``.txt`` / ``.pdf``).

Design (drop-in books, Phase 2b):

* **``.txt`` / ``.md`` always work** with zero dependencies — a plain UTF-8 read (errors
  replaced), exactly as the curated corpus is stored today.
* **``.pdf`` uses PyMuPDF (``fitz``)** — a ~20 MB binary wheel that is fast, fully offline,
  and needs no model download. It is an OPTIONAL dependency (``dr-alex[pdf]``). If it is
  not installed, ``.txt`` books keep working and a PDF prints a single install hint rather
  than crashing anything.
* **Extraction is cached.** A PDF is extracted once to a ``<stem>.extracted.txt`` sibling in
  the corpus dir; that cache is what gets indexed, so re-ingest is cheap and the derived
  cache is gitignored (never committed).

No subprocesses are spawned here (Directive 1): ``fitz`` is an in-process library call.
"""

from __future__ import annotations

from pathlib import Path

# Marks a derived extraction cache so auto-discovery never treats it as a primary source.
EXTRACTED_SUFFIX = ".extracted.txt"

PDF_INSTALL_HINT = (
    "PDF support needs PyMuPDF (offline, ~20MB binary wheel). "
    "Install it with:  uv add pymupdf   (or: uv pip install pymupdf)"
)

_TEXT_SUFFIXES = frozenset({".txt", ".md", ".text"})


class PdfLibraryMissing(RuntimeError):
    """Raised when a PDF must be extracted but PyMuPDF (``fitz``) isn't installed."""

    def __init__(self, message: str = PDF_INSTALL_HINT) -> None:
        super().__init__(message)


def pdf_support() -> bool:
    """True when PyMuPDF is importable (PDF extraction is available)."""
    try:
        import fitz  # noqa: F401  (PyMuPDF)
    except ImportError:
        return False
    return True


def is_pdf(path: Path | str) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def is_extraction_cache(path: Path | str) -> bool:
    return Path(path).name.lower().endswith(EXTRACTED_SUFFIX)


def _extract_pdf(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - exercised via pdf_support() gate
        raise PdfLibraryMissing() from exc
    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def extract_text(path: Path | str) -> str:
    """Extract plain text from a book file.

    ``.txt`` / ``.md`` are read directly; ``.pdf`` goes through PyMuPDF (raising
    :class:`PdfLibraryMissing` if the lib is absent). Any other suffix is read as text
    (best effort). Never raises for text files.
    """
    p = Path(path)
    if is_pdf(p):
        return _extract_pdf(p)
    return p.read_text(encoding="utf-8", errors="replace")


def cache_path(source: Path | str, corpus_dir: Path | str) -> Path:
    """The extraction-cache path for a PDF ``source`` inside ``corpus_dir``."""
    stem = Path(source).stem
    return Path(corpus_dir) / f"{stem}{EXTRACTED_SUFFIX}"


def extract_to_cache(source: Path | str, corpus_dir: Path | str) -> Path:
    """Extract a PDF to its ``<stem>.extracted.txt`` cache and return the cache path.

    Idempotent enough for re-ingest: always rewrites the cache from the current source.
    Raises :class:`PdfLibraryMissing` when PyMuPDF is unavailable.
    """
    src = Path(source)
    out = cache_path(src, corpus_dir)
    text = extract_text(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
