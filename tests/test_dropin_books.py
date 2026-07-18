"""Drop-in books (Phase 2b): add a book by dropping a file + one command.

Covers: PDF text extraction (real tiny synthetic PDF + graceful-when-missing), the
supplemental user-manifest merge, auto-discovery of loose files, the broken-extraction
guard (mirrors the Beck exclusion), a malformed user manifest that is skipped without
crashing ingest, and a REAL end-to-end add→retrieve.

Isolation: every test points the corpus + index dirs at tmp locations and empties the
curated core (``manifest._BOOKS``) so only drop-in behavior is exercised — the suite never
touches the real 13-book library or the real ``data/index``.
"""

from __future__ import annotations

import json
import logging

import pytest

from books import dropin, extract, manifest, retriever
from books.manifest import BookSpec
from books.retriever import BookRetriever

_LOG = "dr_alex.books"


def _long(word: str, n: int = 500) -> str:
    """A body comfortably over MIN_USABLE_CHARS with a distinctive lead word."""
    return (word + " mindful breathing attention practice present moment. ") * n


def _make_pdf(path, phrase: str, pages: int = 6) -> None:
    import fitz  # PyMuPDF

    para = (phrase + " ") + ("clinical grounding technique breathing skill exercise. " * 30)
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(36, 36, 560, 760), para, fontsize=10)
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    c = tmp_path / "corpus"
    c.mkdir()
    monkeypatch.setenv("DR_ALEX_BOOKS_DIR", str(c))
    monkeypatch.setenv("DR_ALEX_INDEX_DIR", str(tmp_path / "index"))
    # Exercise ONLY drop-in behavior against a clean corpus (no curated core files present).
    monkeypatch.setattr(manifest, "_BOOKS", ())
    return c


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not extract.pdf_support(), reason="PyMuPDF not installed")
def test_pdf_extraction_happy_path(tmp_path):
    p = tmp_path / "chem.pdf"
    _make_pdf(p, "Hydrogen sodium potassium calcium magnesium", pages=2)
    text = extract.extract_text(p)
    assert "Hydrogen" in text
    assert "potassium" in text
    assert len(text) > 1000


@pytest.mark.skipif(not extract.pdf_support(), reason="PyMuPDF not installed")
def test_extract_to_cache_writes_sibling(tmp_path, corpus):
    src = corpus / "handbook.pdf"
    _make_pdf(src, "Photosynthesis chloroplast membrane", pages=2)
    cache = extract.extract_to_cache(src, corpus)
    assert cache.name == "handbook.extracted.txt"
    assert cache.parent == corpus
    assert "Photosynthesis" in cache.read_text(encoding="utf-8")
    assert extract.is_extraction_cache(cache)


def test_pdf_without_lib_is_graceful(corpus, monkeypatch, caplog):
    # Simulate PyMuPDF not installed: .txt still works, a PDF is skipped with an install hint.
    monkeypatch.setattr(extract, "pdf_support", lambda: False)
    (corpus / "scanned.pdf").write_bytes(b"%PDF-1.4 not really extractable")
    (corpus / "notes.txt").write_text(_long("alphaword"), encoding="utf-8")

    # add_book raises the typed error (the CLI turns it into a one-line hint, never a crash).
    with pytest.raises(extract.PdfLibraryMissing):
        dropin.add_book(corpus / "scanned.pdf")

    with caplog.at_level(logging.WARNING, logger=_LOG):
        results = dropin.discover()
    slugs = [r.slug for r in results]
    assert "notes" in slugs           # .txt still discovered
    assert "scanned" not in slugs     # .pdf skipped, not crashed
    assert "PDF support" in caplog.text


# ---------------------------------------------------------------------------
# User-manifest merge
# ---------------------------------------------------------------------------


def test_user_manifest_entry_merges_into_included(corpus):
    (corpus / "cache.txt").write_text(_long("betaword"), encoding="utf-8")
    manifest.register_user_book(
        BookSpec(slug="beta-book", title="Beta Book", short_title="Beta",
                 authors="B. Author", filename="cache.txt")
    )
    included = manifest.included_books()
    slugs = [b.slug for b in included]
    assert "beta-book" in slugs
    (spec,) = [b for b in included if b.slug == "beta-book"]
    assert spec.origin == "user"
    assert manifest.by_slug("beta-book").title == "Beta Book"


def test_malformed_entry_skipped_valid_entry_kept(corpus, caplog):
    manifest.user_manifest_path().write_text(
        json.dumps({"books": [
            {"slug": "bad"},  # missing title + filename
            {"slug": "okentry", "title": "OK Entry", "filename": "okentry.txt"},
        ]}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger=_LOG):
        specs = manifest.user_books()
    assert [s.slug for s in specs] == ["okentry"]
    assert "skipped" in caplog.text.lower()


def test_malformed_user_manifest_skipped_and_ingest_survives(corpus, caplog):
    manifest.user_manifest_path().write_text("{ this is : not valid json", encoding="utf-8")
    (corpus / "good.txt").write_text(_long("thetaword"), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=_LOG):
        skipped = manifest.user_books()          # malformed → () + WARN
        stats = retriever.build_index()          # must NOT crash
    assert skipped == ()
    assert "skipped entirely" in caplog.text.lower()
    assert stats.books_indexed >= 1              # ingest succeeded on the good loose file
    assert "good" in stats.discovered


# ---------------------------------------------------------------------------
# Auto-discovery ("drop a file in the folder, run ingest")
# ---------------------------------------------------------------------------


def test_drop_in_txt_is_discovered_indexed_and_retrievable(corpus):
    phrase = "quokkalicious anchor phrase marker"
    (corpus / "Dropped Book.txt").write_text(phrase + " " + _long("gammaword"), encoding="utf-8")

    stats = retriever.build_index()
    assert "dropped-book" in stats.discovered
    assert stats.books_indexed == 1

    hits = BookRetriever().retrieve("quokkalicious anchor", k=3)
    assert hits, "distinctive phrase did not surface"
    assert hits[0].book_slug == "dropped-book"

    # Registered persistently (shows up on the next status/ingest without re-dropping).
    assert "dropped-book" in [b.slug for b in manifest.included_books()]


def test_reingest_does_not_duplicate_discovered_book(corpus):
    (corpus / "steady.txt").write_text(_long("deltaword"), encoding="utf-8")
    first = retriever.build_index()
    assert first.discovered == ["steady"]
    second = retriever.build_index()
    assert second.discovered == []               # already registered → not re-discovered
    assert second.books_indexed == first.books_indexed == 1


# ---------------------------------------------------------------------------
# Broken-extraction guard (mirror the Beck exclusion)
# ---------------------------------------------------------------------------


def test_short_extraction_is_excluded_and_warns(corpus, caplog):
    (corpus / "Stub Fragment.txt").write_text("too short to be a real book", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=_LOG):
        stats = retriever.build_index()
    assert stats.warned_excluded is True
    assert stats.books_indexed == 0              # never silently indexed
    titles = [t for t, _ in stats.excluded]
    assert any("Stub Fragment" in t for t in titles)
    assert "not indexed" in caplog.text.lower()
    # It is registered as EXCLUDED with a reason, not dropped on the floor.
    excluded_slugs = [b.slug for b in manifest.excluded_books()]
    assert "stub-fragment" in excluded_slugs


# ---------------------------------------------------------------------------
# End-to-end via the CLI: `dr-alex books add <file>` → retrieve
# ---------------------------------------------------------------------------


def test_cli_books_add_txt_then_retrieve(corpus, tmp_path, capsys):
    from dr_alex import cli

    external = tmp_path / "External Notes.txt"
    phrase = "xylophone resonance distinctive marker"
    external.write_text(phrase + " " + _long("epsilonword"), encoding="utf-8")

    rc = cli.main(["books", "add", str(external), "--title", "My Field Notes",
                   "--authors", "Prax"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Added:" in out and "My Field Notes" in out

    hits = BookRetriever().retrieve("xylophone resonance", k=3)
    assert hits and hits[0].book_slug == "my-field-notes"
    # The source was copied into the corpus dir (drop-in self-contained).
    assert (corpus / "External Notes.txt").exists()


@pytest.mark.skipif(not extract.pdf_support(), reason="PyMuPDF not installed")
def test_cli_books_add_pdf_then_retrieve(corpus, tmp_path, capsys):
    from dr_alex import cli

    external_pdf = tmp_path / "Zephyr Manual.pdf"
    _make_pdf(external_pdf, "zephyrine calibration distinctive marker", pages=6)

    rc = cli.main(["books", "add", str(external_pdf)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Added:" in out

    # A .extracted.txt cache sits next to the copied source in the corpus dir.
    assert (corpus / "Zephyr Manual.pdf").exists()
    assert (corpus / "Zephyr Manual.extracted.txt").exists()

    hits = BookRetriever().retrieve("zephyrine calibration", k=3)
    assert hits and hits[0].book_slug == "zephyr-manual"


def test_cli_books_status_shows_user_book(corpus, capsys):
    from dr_alex import cli

    (corpus / "handbook.txt").write_text(_long("zetaword"), encoding="utf-8")
    manifest.register_user_book(
        BookSpec(slug="handbook", title="The Handbook", short_title="Handbook",
                 authors="A", filename="handbook.txt")
    )
    rc = cli.main(["books", "status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[user]" in out
    assert "handbook" in out
    assert "user-added: 1" in out
