"""Retriever: BM25 default, honest emptiness, and the pluggable hybrid embedder slot.

These are hermetic — a tiny synthetic corpus is indexed in a tmp dir. The real-corpus
smoke tests (thought record / opposite action / body scan) live in test_corpus_smoke.py.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import pytest

from books import retriever
from books.manifest import BookSpec
from books.retriever import BookRetriever, Embedder, RetrievedChunk

_ALPHA = (
    "Mindfulness is paying attention on purpose. "
    + ("Breathing meditation awareness present moment practice. " * 60)
    + "A quiet lighthouse stands over the calm water. "
    + ("Sitting with the breath, noticing thoughts come and go. " * 60)
)
_BETA = (
    "Procrastination is the gap between intention and action. "
    + ("Deadline motivation delay task avoidance willpower. " * 80)
)


@pytest.fixture()
def tiny(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha.txt").write_text(_ALPHA, encoding="utf-8")
    (corpus / "beta.txt").write_text(_BETA, encoding="utf-8")
    specs = (
        BookSpec(slug="alpha", title="Alpha Book", short_title="Alpha",
                 authors="A. One", filename="alpha.txt"),
        BookSpec(slug="beta", title="Beta Book", short_title="Beta",
                 authors="B. Two", filename="beta.txt"),
    )
    excluded = (
        BookSpec(slug="broken", title="Broken Book", short_title="Broken",
                 authors="X", filename=None, included=False,
                 exclusion_reason="no usable text — broken extraction"),
    )
    monkeypatch.setattr(retriever.manifest, "included_books", lambda: specs)
    monkeypatch.setattr(retriever.manifest, "excluded_books", lambda: excluded)
    db = tmp_path / "index" / "books.db"
    stats = retriever.build_index(index_file=db, corpus_dir=corpus)
    return db, stats


# ---------------------------------------------------------------------------
# Build + WARN
# ---------------------------------------------------------------------------


def test_build_indexes_included_and_sets_perms(tiny) -> None:
    db, stats = tiny
    assert stats.books_indexed == 2
    assert stats.total_chunks > 0
    assert db.exists()
    import os
    assert oct(os.stat(db).st_mode)[-3:] == "600"
    assert oct(os.stat(db.parent).st_mode)[-3:] == "700"


def test_build_warns_loudly_for_excluded(tmp_path, monkeypatch, caplog) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "alpha.txt").write_text(_ALPHA, encoding="utf-8")
    specs = (BookSpec(slug="alpha", title="Alpha Book", short_title="Alpha",
                      authors="A", filename="alpha.txt"),)
    excluded = (BookSpec(slug="broken", title="Broken Book", short_title="Broken",
                         authors="X", filename=None, included=False,
                         exclusion_reason="no usable text — broken extraction"),)
    monkeypatch.setattr(retriever.manifest, "included_books", lambda: specs)
    monkeypatch.setattr(retriever.manifest, "excluded_books", lambda: excluded)
    with caplog.at_level(logging.WARNING, logger="dr_alex.books"):
        stats = retriever.build_index(index_file=tmp_path / "i" / "books.db", corpus_dir=corpus)
    assert stats.warned_excluded is True
    assert ("Broken Book", "no usable text — broken extraction") in stats.excluded
    assert "Broken Book" in caplog.text
    assert "not indexed" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Retrieval — BM25 default
# ---------------------------------------------------------------------------


def test_retrieve_returns_right_book(tiny) -> None:
    db, _ = tiny
    r = BookRetriever(index_file=db)
    hits = r.retrieve("mindfulness meditation", k=3)
    assert hits
    assert hits[0].book_slug == "alpha"
    assert hits[0].score > 0
    # Plain-prose fake books have no detected structure → chapter is None (fallback).
    assert hits[0].chapter is None

    hits2 = r.retrieve("procrastination deadline", k=3)
    assert hits2 and hits2[0].book_slug == "beta"


def test_retrieve_fields_shape(tiny) -> None:
    db, _ = tiny
    hit = BookRetriever(index_file=db).retrieve("mindfulness", k=1)[0]
    assert isinstance(hit, RetrievedChunk)
    assert hit.chunk_id.startswith("alpha:")
    assert hit.book_title == "Alpha Book"
    assert hit.text


def test_empty_query_returns_empty(tiny) -> None:
    db, _ = tiny
    r = BookRetriever(index_file=db)
    assert r.retrieve("") == []
    assert r.retrieve("   ") == []
    assert r.retrieve("the of to", k=3) == []  # only stopwords
    assert r.retrieve("mindfulness", k=0) == []


def test_missing_index_returns_empty(tmp_path) -> None:
    r = BookRetriever(index_file=tmp_path / "nope.db")
    assert r.retrieve("anything") == []


def test_index_status(tiny) -> None:
    db, stats = tiny
    st = retriever.index_status(db)
    assert st.exists
    assert st.total_chunks == stats.total_chunks
    assert set(st.per_book) == {"alpha", "beta"}


def test_missing_index_status(tmp_path) -> None:
    st = retriever.index_status(tmp_path / "nope.db")
    assert st.exists is False
    assert st.total_chunks == 0


# ---------------------------------------------------------------------------
# Pluggable embedder — the hybrid slot
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """A tiny deterministic stand-in: texts containing ``key`` embed near the query."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[1.0, 0.0] if self.key in t.lower() else [0.0, 1.0] for t in texts]


def test_fake_embedder_satisfies_protocol() -> None:
    assert isinstance(FakeEmbedder("x"), Embedder)


def test_hybrid_slot_is_wired_into_retrieve(tiny) -> None:
    db, _ = tiny
    fake = FakeEmbedder("lighthouse")
    r = BookRetriever(index_file=db, embedder=fake)
    hits = r.retrieve("mindfulness lighthouse", k=3)
    assert hits
    # The embedder was consulted: at least the query + the candidate batch.
    assert len(fake.calls) >= 2


def test_hybrid_rerank_reorders_by_embedder() -> None:
    # BM25 puts cA first; the embedder must be able to promote the semantic match cB.
    cA = RetrievedChunk("a:0", "a", "A Book", None, "A", "generic wellness text", score=9.0)
    cB = RetrievedChunk("b:0", "b", "B Book", None, "B", "the hidden target passage", score=1.0)
    fake = FakeEmbedder("target")
    r = BookRetriever(embedder=fake, hybrid_alpha=0.0)  # trust the embedder entirely
    out = r._rerank("please find the target", [cA, cB], k=2)
    assert [c.chunk_id for c in out][0] == "b:0"
    assert fake.calls  # embedder actually ran


def test_bm25_only_default_ignores_embedder_path(tiny) -> None:
    db, _ = tiny
    r = BookRetriever(index_file=db)  # embedder is None by default
    assert r.embedder is None
    hits = r.retrieve("mindfulness", k=2)
    assert hits and hits[0].book_slug == "alpha"
