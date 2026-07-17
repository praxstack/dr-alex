"""Corpus manifest: 13 included books + the excluded Beck extraction."""

from __future__ import annotations

from books import manifest


def test_thirteen_included_one_excluded() -> None:
    assert len(manifest.included_books()) == 13
    assert len(manifest.excluded_books()) == 1
    assert len(manifest.all_books()) == 14


def test_excluded_is_beck_with_reason() -> None:
    (beck,) = manifest.excluded_books()
    assert "Beck" in beck.authors or "beck" in beck.slug
    assert beck.included is False
    assert beck.filename is None
    # The reason must be explicit — never silently indexed.
    assert beck.exclusion_reason
    assert "no usable" in beck.exclusion_reason.lower()


def test_included_books_have_real_corpus_files() -> None:
    corpus = manifest.corpus_dir()
    for spec in manifest.included_books():
        assert spec.filename, f"{spec.slug} missing filename"
        assert (corpus / spec.filename).exists(), f"{spec.slug}: corpus file missing"


def test_slugs_and_titles_unique() -> None:
    slugs = [b.slug for b in manifest.all_books()]
    titles = [b.title for b in manifest.all_books()]
    assert len(slugs) == len(set(slugs))
    assert len(titles) == len(set(titles))


def test_by_slug_roundtrip() -> None:
    assert manifest.by_slug("feeling-good").short_title == "Feeling Good"
    assert manifest.by_slug("nonexistent") is None
