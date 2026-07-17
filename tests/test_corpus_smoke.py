"""Real-corpus smoke tests (council D1: verify on the ACTUAL library).

Builds the index from the real 13-book corpus once (module-scoped) into a tmp dir and
asserts that canonical clinical concepts surface their origin book. Skips cleanly if the
corpus export isn't present on this machine, so the suite stays runnable anywhere.
"""

from __future__ import annotations

import pytest

from books import manifest, retriever
from books.retriever import BookRetriever


def _corpus_present() -> bool:
    corpus = manifest.corpus_dir()
    return all((corpus / s.filename).exists() for s in manifest.included_books())


pytestmark = pytest.mark.skipif(
    not _corpus_present(), reason="real book corpus not available on this machine"
)


@pytest.fixture(scope="module")
def real_index(tmp_path_factory):
    db = tmp_path_factory.mktemp("real_index") / "books.db"
    stats = retriever.build_index(index_file=db)
    return db, stats


def test_full_corpus_ingest_counts(real_index) -> None:
    _db, stats = real_index
    # 13 included books, the Beck extraction excluded + warned.
    assert stats.books_indexed == 13
    assert stats.total_chunks > 1500
    assert stats.warned_excluded is True
    assert any("Cognitive Therapy of Depression" in title for title, _ in stats.excluded)


@pytest.mark.parametrize(
    ("query", "want_slug"),
    [
        ("thought record", "feeling-good"),
        ("opposite action", "dbt-skills-workbook"),
        ("body scan", "mindful-way"),
    ],
)
def test_concept_surfaces_origin_book(real_index, query, want_slug) -> None:
    db, _ = real_index
    hits = BookRetriever(index_file=db).retrieve(query, k=3)
    assert hits, f"no hits for {query!r}"
    slugs = [h.book_slug for h in hits]
    assert want_slug in slugs, f"{query!r} -> {slugs}, expected {want_slug} in top-3"


def test_no_page_numbers_leak_into_metadata(real_index) -> None:
    # Sources have no page numbers; chapter labels must never fabricate one.
    db, _ = real_index
    hits = BookRetriever(index_file=db).retrieve("cognitive distortion", k=5)
    for h in hits:
        if h.chapter:
            assert "page" not in h.chapter.lower()
