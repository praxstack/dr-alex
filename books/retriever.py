"""Book retrieval — a local SQLite FTS5/BM25 index over the clinical library.

Design (council D1, binding):

* **BM25 by default, no heavy deps.** The index is plain SQLite FTS5; there is no
  torch, no model download, no network. Ranking is BM25 over the *breadcrumb-prefixed*
  chunk text (poor-man's contextual retrieval — the chapter breadcrumb is part of what
  gets scored, so "distress tolerance" pulls the DBT chapter even when the exact words
  are sparse in the body).
* **Pluggable Embedder seam.** ``BookRetriever(embedder=...)`` turns on a hybrid
  re-rank: BM25 selects candidates, the embedder re-orders them by cosine similarity.
  The default embedder is ``None`` (pure BM25). A fake embedder exercises the slot in
  the test-suite; no real model is ever required.
* **Derived + rebuildable.** The DB lives at ``data/index/books.db`` (gitignored, 0700
  parent). It is fully reconstructable from the corpus via ``build_index`` /
  ``dr-alex books ingest`` and never committed.
* **Honest emptiness.** A missing index, an empty query, or an FTS syntax error yields
  ``[]`` — Dr. Alex says nothing rather than fabricating a source.

The excluded 14th book (Beck, broken 876-char extraction) is *never* indexed; the
manifest drives ingestion and ``build_index`` emits a loud WARN for it.
"""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from books import manifest
from books.chunker import Chunk, chunk_book, indexed_text

log = logging.getLogger("dr_alex.books")

_REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR_ENV = "DR_ALEX_INDEX_DIR"

# BM25 candidate pool multiplier for the hybrid re-rank slot.
_CANDIDATE_FACTOR = 4
_MIN_CANDIDATES = 20

# Tiny stop list — words too common to help select a book.
_STOP = frozenset(
    ["a", "an", "and", "the", "of", "to", "in", "on", "for", "with", "is", "are", "be", "it", "this", "that", "i", "you", "my", "me", "we", "our", "how", "what", "when", "where", "why", "can", "do", "does", "about", "into", "over", "under", "from", "as", "at", "or"]
)


# ---------------------------------------------------------------------------
# Public data + embedder seam
# ---------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Pluggable dense-embedding backend for the hybrid re-rank slot.

    Any object with an ``embed`` returning one vector per input text satisfies this.
    The default retriever runs BM25-only (``embedder=None``); supplying an Embedder
    turns on candidate re-ranking. Implementations must be local and dependency-light —
    no model downloads happen inside this package.
    """

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieved unit of evidence. ``chapter`` is ``None`` for fallback books."""

    chunk_id: str
    book_slug: str
    book_title: str
    chapter: str | None
    breadcrumb: str
    text: str
    score: float


@dataclass
class IngestStats:
    index_path: Path
    per_book: dict[str, int] = field(default_factory=dict)
    total_chunks: int = 0
    excluded: list[tuple[str, str]] = field(default_factory=list)  # (title, reason)
    warned_excluded: bool = False
    discovered: list[str] = field(default_factory=list)  # slugs auto-registered this build

    @property
    def books_indexed(self) -> int:
        return len(self.per_book)


# ---------------------------------------------------------------------------
# Index location
# ---------------------------------------------------------------------------


def index_dir() -> Path:
    override = os.environ.get(INDEX_DIR_ENV)
    return Path(override) if override else _REPO_ROOT / "data" / "index"


def index_path() -> Path:
    return index_dir() / "books.db"


def index_exists(path: Path | None = None) -> bool:
    return (path or index_path()).exists()


# ---------------------------------------------------------------------------
# FTS query construction
# ---------------------------------------------------------------------------


# Curated clinical-technique expansions — a transparent, dependency-free "poor-man's
# semantic" layer that complements the breadcrumb trick. A therapy concept is often
# named differently across books (Burns' "Daily Record of Dysfunctional Thoughts" IS the
# "thought record"; the phrase "thought record" never appears in *Feeling Good*). When a
# query names a known technique, we search its canonical variants as FTS phrases so the
# *origin* book surfaces even without dense embeddings. Values are space-separated,
# tokenizer-safe phrases (hyphens/punctuation removed). This is a curated aid, not magic;
# unknown queries fall through to ordinary phrase/AND/OR matching.
_TECHNIQUE_EXPANSIONS: dict[str, list[str]] = {
    "thought record": [
        "thought record", "daily record", "dysfunctional thought",
        "automatic thought", "cognitive restructuring",
    ],
    "cognitive distortion": [
        "cognitive distortion", "thinking error", "distorted thinking",
        "cognitive restructuring",
    ],
    "behavioral activation": [
        "behavioral activation", "behavioural activation", "activity schedule",
        "pleasant activities",
    ],
    "opposite action": ["opposite action", "acting opposite"],
    "body scan": ["body scan", "bodyscan"],
    "urge surfing": ["urge surfing", "urge surf", "surfing the urge"],
    "distress tolerance": ["distress tolerance", "radical acceptance", "self soothe"],
    "self compassion": ["self compassion", "loving kindness", "common humanity"],
    "implementation intention": ["implementation intention", "if then plan"],
    "grounding": ["grounding", "five senses", "present moment"],
}


def _terms(query: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", query.lower())
    return [t for t in toks if len(t) > 1 and t not in _STOP]


def _match_technique(query: str) -> str | None:
    """The most-specific known technique whose words all appear in ``query``."""
    words = set(re.findall(r"[a-z]+", query.lower()))
    best: str | None = None
    for key in _TECHNIQUE_EXPANSIONS:
        if all(w in words for w in key.split()) and (best is None or len(key) > len(best)):
            best = key
    return best


def _phrase(words: Sequence[str]) -> str:
    return '"' + " ".join(words) + '"'


def _match_candidates(query: str) -> list[str]:
    """FTS5 MATCH expressions to try, in priority order (first with hits wins).

    Order: curated technique expansion → exact phrase → AND → OR. Precision first,
    recall as a fallback.
    """
    terms = _terms(query)
    if not terms:
        return []
    cands: list[str] = []
    key = _match_technique(query)
    if key:
        cands.append(" OR ".join(_phrase(v.split()) for v in _TECHNIQUE_EXPANSIONS[key]))
    if len(terms) >= 2:
        cands.append(_phrase(terms))     # exact phrase of the query's content words
        cands.append(" ".join(terms))    # implicit AND
        cands.append(" OR ".join(terms))  # OR (recall)
    else:
        cands.append(terms[0])
    return cands


# ---------------------------------------------------------------------------
# Building the index
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE chunks(
    id         INTEGER PRIMARY KEY,
    chunk_id   TEXT NOT NULL UNIQUE,
    book_slug  TEXT NOT NULL,
    book_title TEXT NOT NULL,
    chapter    TEXT,
    breadcrumb TEXT NOT NULL,
    body       TEXT NOT NULL
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    indexed_text,
    content='',
    tokenize='porter unicode61'
);
"""


def _read_book(spec: manifest.BookSpec, corpus_dir: Path) -> str:
    path = corpus_dir / spec.filename  # type: ignore[operator]
    return path.read_text(encoding="utf-8", errors="replace")


def build_index(
    *,
    index_file: Path | None = None,
    corpus_dir: Path | None = None,
) -> IngestStats:
    """(Re)build the FTS5/BM25 index from the corpus. Fully rebuildable + idempotent.

    Emits a loud WARN for every excluded book (the broken Beck extraction) so it can
    never be silently indexed. Returns ingest statistics.
    """
    index_file = index_file or index_path()
    corpus_dir = corpus_dir or manifest.corpus_dir()

    index_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(index_file.parent, 0o700)
    except OSError:  # pragma: no cover - best effort on odd filesystems
        pass

    # Fully rebuildable: drop any prior db + WAL/SHM siblings first.
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(index_file) + suffix)
        if p.exists():
            p.unlink()

    stats = IngestStats(index_path=index_file)

    # Auto-discovery: register any loose .txt/.pdf dropped into the corpus that no manifest
    # yet knows about, so "drop a file in the folder, run ingest" just works. Registration
    # persists to the user manifest; the included/excluded loops below then pick it up.
    from books import dropin  # local import keeps the package import graph acyclic

    for res in dropin.discover(corpus_dir):
        stats.discovered.append(res.slug)

    # Excluded books (curated Beck extraction + any short/broken drop-ins): WARN, never index.
    for spec in manifest.excluded_books():
        stats.excluded.append((spec.title, spec.exclusion_reason or "excluded"))
        stats.warned_excluded = True
        log.warning(
            "CORPUS EXCLUSION: %r is NOT indexed — %s",
            spec.title,
            spec.exclusion_reason,
        )

    conn = sqlite3.connect(index_file)
    try:
        conn.executescript(_SCHEMA)
        next_id = 1
        for spec in manifest.included_books():
            try:
                text = _read_book(spec, corpus_dir)
            except OSError as exc:
                # A registered book whose file vanished must fail loudly, never silently
                # drop out: treat it exactly like the broken-extraction guard below.
                reason = f"source file unreadable ({spec.filename!r}): {exc}"
                stats.excluded.append((spec.title, reason))
                stats.warned_excluded = True
                log.warning("CORPUS EXCLUSION: %r is NOT indexed — %s", spec.title, reason)
                continue
            # Broken-extraction guard (mirrors the Beck exclusion): never silently index a
            # book with no usable text — WARN loudly and mark it excluded instead.
            if len(text.strip()) < manifest.MIN_USABLE_CHARS:
                reason = manifest.broken_extraction_reason(len(text.strip()))
                stats.excluded.append((spec.title, reason))
                stats.warned_excluded = True
                log.warning("CORPUS EXCLUSION: %r is NOT indexed — %s", spec.title, reason)
                continue
            chunks: list[Chunk] = chunk_book(spec, text)
            rows = []
            fts_rows = []
            for ch in chunks:
                rows.append(
                    (next_id, ch.chunk_id, ch.book_slug, ch.book_title,
                     ch.chapter, ch.breadcrumb, ch.text)
                )
                fts_rows.append((next_id, indexed_text(ch)))
                next_id += 1
            conn.executemany(
                "INSERT INTO chunks(id, chunk_id, book_slug, book_title, chapter, "
                "breadcrumb, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.executemany(
                "INSERT INTO chunks_fts(rowid, indexed_text) VALUES (?, ?)",
                fts_rows,
            )
            stats.per_book[spec.slug] = len(chunks)
            stats.total_chunks += len(chunks)
        conn.commit()
    finally:
        conn.close()

    try:
        os.chmod(index_file, 0o600)
    except OSError:  # pragma: no cover
        pass

    return stats


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@dataclass
class IndexStatus:
    exists: bool
    path: Path
    total_chunks: int = 0
    per_book: dict[str, int] = field(default_factory=dict)


def index_status(index_file: Path | None = None) -> IndexStatus:
    index_file = index_file or index_path()
    if not index_file.exists():
        return IndexStatus(exists=False, path=index_file)
    conn = sqlite3.connect(index_file)
    try:
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        per_book = dict(
            conn.execute(
                "SELECT book_slug, COUNT(*) FROM chunks GROUP BY book_slug"
            ).fetchall()
        )
    except sqlite3.Error:  # pragma: no cover - corrupt/foreign db
        return IndexStatus(exists=True, path=index_file)
    finally:
        conn.close()
    return IndexStatus(exists=True, path=index_file, total_chunks=total, per_book=per_book)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


class BookRetriever:
    """Query the book index. BM25 by default; hybrid re-rank when an Embedder is set."""

    def __init__(
        self,
        *,
        index_file: Path | None = None,
        embedder: Embedder | None = None,
        hybrid_alpha: float = 0.5,
    ) -> None:
        self.index_file = index_file or index_path()
        self.embedder = embedder
        self.hybrid_alpha = hybrid_alpha

    # -- BM25 candidate fetch ------------------------------------------------

    def _bm25(self, query: str, limit: int) -> list[RetrievedChunk]:
        sql = (
            "SELECT c.chunk_id, c.book_slug, c.book_title, c.chapter, c.breadcrumb, "
            "c.body, bm25(chunks_fts) AS score "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?"
        )
        conn = sqlite3.connect(self.index_file)
        try:
            for expr in _match_candidates(query):  # precise → recall; first hit wins
                try:
                    rows = conn.execute(sql, (expr, limit)).fetchall()
                except sqlite3.Error:
                    rows = []
                if rows:
                    # bm25() is more-negative-is-better; expose a positive relevance.
                    return [
                        RetrievedChunk(
                            chunk_id=r[0], book_slug=r[1], book_title=r[2],
                            chapter=r[3], breadcrumb=r[4], text=r[5], score=-float(r[6]),
                        )
                        for r in rows
                    ]
            return []
        finally:
            conn.close()

    # -- hybrid re-rank ------------------------------------------------------

    def _rerank(self, query: str, cands: list[RetrievedChunk], k: int) -> list[RetrievedChunk]:
        assert self.embedder is not None
        qv = self.embedder.embed([query])[0]
        cvs = self.embedder.embed([c.text for c in cands])
        bm = _minmax([c.score for c in cands])
        sims = [_cosine(qv, cv) for cv in cvs]
        sim_n = _minmax(sims)
        a = self.hybrid_alpha
        combined = [a * b + (1 - a) * s for b, s in zip(bm, sim_n, strict=False)]
        order = sorted(range(len(cands)), key=lambda i: combined[i], reverse=True)
        return [
            RetrievedChunk(
                chunk_id=cands[i].chunk_id, book_slug=cands[i].book_slug,
                book_title=cands[i].book_title, chapter=cands[i].chapter,
                breadcrumb=cands[i].breadcrumb, text=cands[i].text, score=combined[idx],
            )
            for idx, i in enumerate(order[:k])
        ]

    # -- public API ----------------------------------------------------------

    def retrieve(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Top-k evidence chunks for ``query``. Returns ``[]`` when nothing fits."""
        if not query or not query.strip() or k <= 0:
            return []
        if not self.index_file.exists():
            return []
        if not _terms(query):
            return []
        pool = max(k * _CANDIDATE_FACTOR, _MIN_CANDIDATES) if self.embedder else k
        cands = self._bm25(query, pool)
        if not cands:
            return []
        if self.embedder is None:
            return cands[:k]
        return self._rerank(query, cands, k)
